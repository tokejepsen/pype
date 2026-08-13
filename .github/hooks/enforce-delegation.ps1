#requires -Version 5.1
<#
  OpenPype delegation-enforcement hook.

  1. Blocks the main Orchestrator from creating/editing any file outside
     docs/. All OpenPype source/config (openpype/, igniter/, server_addon/,
     tools/, vendor/, website/, and root files like start.py/pyproject.toml)
     MUST be changed via a subagent (builder, or test-writer for anything
     under a tests/ folder).
  2. Blocks the main Orchestrator from READING large/generated files (> 50 KB)
     so they never bloat orchestrator context. Delegate those reads to explorer.

  How it distinguishes the orchestrator from a subagent:
    - Subagent tool calls carry agent_id / agent_type in the hook payload -> allow.
    - Otherwise the orchestrator is acting -> block protected edits/reads (exit 2).

  Fails OPEN (exit 0 = allow) on any internal error so a hook bug can never
  brick normal editing. Guidance in AGENTS.md still applies.
#>

$ErrorActionPreference = 'Stop'

function Allow { exit 0 }

try {
    $raw = [Console]::In.ReadToEnd()
    if ([string]::IsNullOrWhiteSpace($raw)) { Allow }
    $data = $raw | ConvertFrom-Json

    $eventName = [string]$data.hook_event_name

    $repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

    # Only enforce on the MAIN thread. Subagent calls carry agent_id / agent_type -> allow.
    $isSubagent = ($data.PSObject.Properties['agent_id']   -and $data.agent_id) -or `
                  ($data.PSObject.Properties['agent_type'] -and $data.agent_type)
    if ($isSubagent) { Allow }

    switch ($eventName) {
        'PreToolUse' {
            $tool = [string]$data.tool_name
            $mutating = $tool -imatch 'create_file|create_directory|replace_string_in_file|multi_replace_string_in_file|insert_edit_into_file|edit_notebook_file|apply_patch|create_new_jupyter_notebook'
            $reading  = $tool -imatch '^(read_file|read_notebook_cell_output)$'
            if (-not $mutating -and -not $reading) { Allow }

            # Gather candidate target paths across known tool-input shapes.
            $paths = New-Object System.Collections.Generic.List[string]
            $ti = $data.tool_input
            if ($ti) {
                foreach ($key in 'filePath', 'dirPath', 'path') {
                    if ($ti.$key) { $paths.Add([string]$ti.$key) }
                }
                if ($ti.replacements) {
                    foreach ($r in $ti.replacements) {
                        if ($r.filePath) { $paths.Add([string]$r.filePath) }
                    }
                }
            }
            if ($paths.Count -eq 0) { Allow }

            $sep = [System.IO.Path]::DirectorySeparatorChar
            $docsRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot 'docs'))

            # --- Read guard: keep the orchestrator from pulling large / generated
            #     files into its own context. Delegate those reads to explorer.
            if ($reading) {
                $maxBytes = 51200  # 50 KB; instruction/config/source files are smaller
                foreach ($p in $paths) {
                    if ([string]::IsNullOrWhiteSpace($p)) { continue }
                    try {
                        if ([System.IO.Path]::IsPathRooted($p)) { $full = [System.IO.Path]::GetFullPath($p) }
                        else { $full = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $p)) }
                    }
                    catch { continue }

                    $big = $false
                    if (Test-Path $full -PathType Leaf) {
                        try { $big = ((Get-Item $full).Length -gt $maxBytes) } catch { $big = $false }
                    }
                    if ($big) {
                        [Console]::Error.WriteLine(
                            "BLOCKED by OpenPype token-hygiene hook: the Orchestrator should not read " +
                            "large/generated files ($([System.IO.Path]::GetFileName($full))). Delegate this read to the " +
                            "'explorer' subagent via runSubagent (agentName: 'explorer') and consume its caveman summary. " +
                            "Attempted: $tool -> $p")
                        exit 2
                    }
                }
                Allow
            }

            # --- Write guard: everything except docs/ must come from a subagent.
            foreach ($p in $paths) {
                if ([string]::IsNullOrWhiteSpace($p)) { continue }
                try {
                    if ([System.IO.Path]::IsPathRooted($p)) {
                        $full = [System.IO.Path]::GetFullPath($p)
                    }
                    else {
                        $full = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $p))
                    }
                }
                catch { continue }

                $isUnderDocs = $full.Equals($docsRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
                               $full.StartsWith($docsRoot + $sep, [System.StringComparison]::OrdinalIgnoreCase)
                if ($isUnderDocs) { continue }

                $isTestPath = $full -split '[\\/]' | Where-Object { $_ -ieq 'tests' } | Select-Object -First 1
                $agent = if ($isTestPath) { 'test-writer' } else { 'builder' }

                [Console]::Error.WriteLine(
                    "BLOCKED by OpenPype delegation hook: the Orchestrator may only edit docs/ directly. " +
                    "Delegate this change to the '$agent' subagent via runSubagent " +
                    "(agentName: '$agent'). Attempted: $tool -> $p")
                exit 2
            }
            Allow
        }
        default { Allow }
    }
}
catch {
    [Console]::Error.WriteLine("OpenPype delegation hook warning (allowing): $($_.Exception.Message)")
    exit 0
}
