# Copy image to clipboard for Desktop injection
# Usage: powershell -ExecutionPolicy Bypass -File copy_image_to_clipboard.ps1 "C:\path\to\image.png"

param(
    [Parameter(Mandatory=$true)]
    [string]$ImagePath
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

if (-not (Test-Path $ImagePath)) {
    Write-Error "Image not found: $ImagePath"
    exit 1
}

try {
    $image = [System.Drawing.Image]::FromFile($ImagePath)
    [System.Windows.Forms.Clipboard]::SetImage($image)
    Write-Host "OK"
    $image.Dispose()
    exit 0
} catch {
    Write-Error "Failed to copy image: $_"
    exit 1
}
