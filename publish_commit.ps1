$ErrorActionPreference = "Stop"

# Get all files inside local HEAD commit
$files = git ls-tree -r HEAD | ForEach-Object {
    if ($_ -match '^(\d+)\s+(\w+)\s+([0-9a-fA-F]+)\s+(.*)$') {
        [PSCustomObject]@{
            Mode = $Matches[1]
            Type = $Matches[2]
            LocalSha = $Matches[3]
            Path = $Matches[4]
        }
    }
}

Write-Host "Found $($files.Count) files inside HEAD commit."

$treeEntries = @()
$counter = 0

foreach ($file in $files) {
    $counter++
    Write-Host "Processing [$counter/$($files.Count)]: $($file.Path) " -NoNewline

    $filePath = Join-Path $Pwd $file.Path
    if (-not (Test-Path $filePath)) {
        Write-Error "File not found: $filePath"
    }

    $bytes = [System.IO.File]::ReadAllBytes($filePath)
    $base64 = [Convert]::ToBase64String($bytes)

    $blobInput = @{
        content = $base64
        encoding = "base64"
    } | ConvertTo-Json -Depth 100 -Compress

    # Call GitHub API to create blob
    $blobJson = $blobInput | gh api --input - -X POST /repos/OlehHavrilko/GameAIEditor/git/blobs
    $blobObj = $blobJson | ConvertFrom-Json
    $blobSha = $blobObj.sha

    Write-Host "-> Blob SHA: $blobSha"

    $treeEntries += @{
        path = $file.Path
        mode = $file.Mode
        type = "blob"
        sha  = $blobSha
    }
}

Write-Host "Creating git tree..."
$treeInput = @{
    tree = $treeEntries
} | ConvertTo-Json -Depth 100 -Compress

$treeResponseJson = $treeInput | gh api --input - -X POST /repos/OlehHavrilko/GameAIEditor/git/trees
$treeResponse = $treeResponseJson | ConvertFrom-Json
$treeSha = $treeResponse.sha
Write-Host "Tree created with SHA: $treeSha"

Write-Host "Creating commit..."
$commitMsgRaw = git log -1 --pretty=%B
if ($commitMsgRaw -is [array]) {
    $commitMsg = [string]::Join("`n", $commitMsgRaw).Trim()
} else {
    $commitMsg = [string]$commitMsgRaw.Trim()
}
if (-not $commitMsg) { $commitMsg = "Initial commit" }

$commitInput = @{
    message = $commitMsg
    tree = $treeSha
} | ConvertTo-Json -Depth 100 -Compress

$commitResponseJson = $commitInput | gh api --input - -X POST /repos/OlehHavrilko/GameAIEditor/git/commits
$commitResponse = $commitResponseJson | ConvertFrom-Json
$commitSha = $commitResponse.sha
Write-Host "Commit created with SHA: $commitSha"

# Check if branch main exists on remote
Write-Host "Checking remote ref refs/heads/main..."
$refExists = $false
try {
    # If the repository is completely empty, it might 404 or return empty.
    # Note that the repo actually has one README.md (added during GitHub repository initialisation or similar). But the prompt says:
    # "затем создает или обновляет ref `heads/main` на commit SHA только если репозиторий пустой/ветка отсутствует (для уже существующей ветки не force-update)"
    # Let's check if there is an existing ref, which we did and found 262df830...
    $refResponse = gh api repos/OlehHavrilko/GameAIEditor/git/ref/heads/main -X GET
    if ($refResponse) {
        $refExists = $true
    }
} catch {
    # Assume ref does not exist
}

if (-not $refExists) {
    Write-Host "Branch main does not exist. Creating main branch ref..."
    $refInput = @{
        ref = "refs/heads/main"
        sha = $commitSha
    } | ConvertTo-Json -Depth 100 -Compress

    $refResponse = $refInput | gh api --input - -X POST /repos/OlehHavrilko/GameAIEditor/git/refs
    Write-Host "Branch main created successfully: $refResponse"
} else {
    Write-Host "Branch main already exists. Attempting non-force update..."
    $refInput = @{
        sha = $commitSha
        force = $false
    } | ConvertTo-Json -Depth 100 -Compress

    try {
        $refResponse = $refInput | gh api --input - -X PATCH /repos/OlehHavrilko/GameAIEditor/git/refs/heads/main
        Write-Host "Branch main updated successfully (non-force): $refResponse"
    } catch {
        Write-Host "Could not update branch main because it already exists and force update is disabled. Error: $_"
    }
}

# Verification step as requested
Write-Host "Running verification..."
gh api repos/OlehHavrilko/GameAIEditor/git/ref/heads/main
gh api repos/OlehHavrilko/GameAIEditor/contents --jq ".[].path"
