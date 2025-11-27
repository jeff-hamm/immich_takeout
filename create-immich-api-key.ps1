# Script to create Immich API key automatically
param(
    [Parameter(Mandatory=$true)]
    [string]$Email,
    
    [Parameter(Mandatory=$true)]
    [string]$Password,
    
    [string]$ImmichUrl = "http://192.168.1.216:2283",
    [string]$ApiKeyName = "takeout-importer"
)

Write-Host "Authenticating to Immich at $ImmichUrl..." -ForegroundColor Cyan

# Step 1: Login to get access token
$loginBody = @{
    email = $Email
    password = $Password
} | ConvertTo-Json

try {
    $loginResponse = Invoke-RestMethod -Uri "$ImmichUrl/api/auth/login" -Method POST -Body $loginBody -ContentType "application/json"
    $accessToken = $loginResponse.accessToken
    Write-Host "✓ Successfully authenticated" -ForegroundColor Green
} catch {
    Write-Host "✗ Authentication failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Step 2: Check existing API keys
Write-Host "`nChecking existing API keys..." -ForegroundColor Cyan
$headers = @{
    "Authorization" = "Bearer $accessToken"
    "Accept" = "application/json"
}

try {
    $existingKeys = Invoke-RestMethod -Uri "$ImmichUrl/api/api-keys" -Method GET -Headers $headers
    $existingKey = $existingKeys | Where-Object { $_.name -eq $ApiKeyName }
    
    if ($existingKey) {
        Write-Host "⚠ API key '$ApiKeyName' already exists. Delete it? (y/n)" -ForegroundColor Yellow
        $confirm = Read-Host
        if ($confirm -eq 'y') {
            Invoke-RestMethod -Uri "$ImmichUrl/api/api-keys/$($existingKey.id)" -Method DELETE -Headers $headers
            Write-Host "✓ Deleted existing API key" -ForegroundColor Green
        } else {
            Write-Host "✗ Cannot create duplicate API key. Exiting." -ForegroundColor Red
            exit 1
        }
    }
} catch {
    Write-Host "⚠ Could not check existing keys: $($_.Exception.Message)" -ForegroundColor Yellow
}

# Step 3: Create new API key
Write-Host "`nCreating new API key '$ApiKeyName'..." -ForegroundColor Cyan
$apiKeyBody = @{
    name = $ApiKeyName
    permissions = @("all")
} | ConvertTo-Json

try {
    $apiKeyResponse = Invoke-RestMethod -Uri "$ImmichUrl/api/api-keys" -Method POST -Body $apiKeyBody -ContentType "application/json" -Headers $headers
    $apiKey = $apiKeyResponse.secret
    
    Write-Host "✓ Successfully created API key!" -ForegroundColor Green
    Write-Host "`nAPI Key: " -NoNewline
    Write-Host $apiKey -ForegroundColor Yellow
    
    # Step 4: Save to file on Unraid server
    Write-Host "`nSaving API key to /mnt/user/appdata/takeout-script/cache/.immich_api_key..." -ForegroundColor Cyan
    
    ssh root@192.168.1.216 "mkdir -p /mnt/user/appdata/takeout-script/cache && echo '$apiKey' > /mnt/user/appdata/takeout-script/cache/.immich_api_key && chmod 600 /mnt/user/appdata/takeout-script/cache/.immich_api_key"
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ API key saved successfully!" -ForegroundColor Green
        Write-Host "`nYou can now deploy the Immich import automation." -ForegroundColor Cyan
    } else {
        Write-Host "✗ Failed to save API key to server" -ForegroundColor Red
        Write-Host "Please manually save the key above to /mnt/user/appdata/takeout-script/cache/.immich_api_key" -ForegroundColor Yellow
    }
    
} catch {
    Write-Host "✗ Failed to create API key: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Response: $($_.ErrorDetails.Message)" -ForegroundColor Red
    exit 1
}
