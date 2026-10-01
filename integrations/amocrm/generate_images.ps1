# Optional Windows asset generator. PNG files are committed; building the ZIP needs only Python.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$assetDirectory = Join-Path $PSScriptRoot 'widget\images'
New-Item -ItemType Directory -Path $assetDirectory -Force | Out-Null

function New-Brush([string] $hex) {
    return [System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml($hex))
}

function Draw-Label($graphics, [string] $text, [float] $size, [float] $x, [float] $y, [string] $color, [bool] $bold = $false) {
    $style = [System.Drawing.FontStyle]::Regular
    if ($bold) { $style = [System.Drawing.FontStyle]::Bold }
    $font = [System.Drawing.Font]::new('Segoe UI', $size, $style, [System.Drawing.GraphicsUnit]::Pixel)
    $brush = New-Brush $color
    $graphics.DrawString($text, $font, $brush, $x, $y)
    $brush.Dispose()
    $font.Dispose()
}

function Draw-ChatIcon($graphics, [float] $x, [float] $y, [float] $size) {
    $green = New-Brush '#166A5C'
    $gold = New-Brush '#DEA45C'
    $white = New-Brush '#FFFFFF'
    $graphics.FillRectangle($green, $x, $y, $size * .76, $size * .57)
    $points = [System.Drawing.PointF[]]@(
        [System.Drawing.PointF]::new($x + $size * .12, $y + $size * .5),
        [System.Drawing.PointF]::new($x + $size * .12, $y + $size * .75),
        [System.Drawing.PointF]::new($x + $size * .4, $y + $size * .5)
    )
    $graphics.FillPolygon($green, $points)
    $graphics.FillRectangle($gold, $x + $size * .42, $y + $size * .48, $size * .58, $size * .41)
    $graphics.FillRectangle($white, $x + $size * .12, $y + $size * .17, $size * .48, $size * .06)
    $graphics.FillRectangle($white, $x + $size * .12, $y + $size * .3, $size * .34, $size * .06)
    $graphics.FillRectangle($white, $x + $size * .54, $y + $size * .63, $size * .31, $size * .06)
    $green.Dispose(); $gold.Dispose(); $white.Dispose()
}

$logos = @{
    'logo_main.png' = @(400, 272)
    'logo_small.png' = @(108, 108)
    'logo.png' = @(130, 100)
    'logo_medium.png' = @(240, 84)
    'logo_min.png' = @(84, 84)
}
foreach ($item in $logos.GetEnumerator()) {
    $width, $height = $item.Value
    $bitmap = [System.Drawing.Bitmap]::new($width, $height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.Clear([System.Drawing.ColorTranslator]::FromHtml('#F5F7F9'))
    $size = [Math]::Min($width, $height) * .64
    if ($item.Key -eq 'logo_medium.png') {
        Draw-ChatIcon $graphics 16 17 54
        Draw-Label $graphics 'LOCAL' 15 86 22 '#263347' $true
        Draw-Label $graphics 'ASSISTANT' 15 86 43 '#166A5C' $true
    } else {
        Draw-ChatIcon $graphics (($width - $size) / 2) (($height - $size) / 2) $size
    }
    $bitmap.Save((Join-Path $assetDirectory $item.Key), [System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose(); $bitmap.Dispose()
}

$tours = @{
    'ru' = @{
        'title' = 'Помощник менеджера'
        'subtitle' = 'Из диалога — в два готовых блока'
        'first' = '1. Откройте помощник'
        'firstDetail' = 'В карточке сделки или в отдельной вкладке'
        'second' = '2. Вставьте диалог'
        'secondDetail' = 'Новое обращение и нужные реплики'
        'third' = '3. Проверьте результат'
        'reply' = 'Ответ клиенту'
        'tip' = 'Подсказка менеджеру'
        'footer' = 'Отправку ответа выполняет менеджер.'
    }
    'en' = @{
        'title' = 'Manager assistant'
        'subtitle' = 'From conversation to two useful blocks'
        'first' = '1. Open the assistant'
        'firstDetail' = 'Inside a lead card or in a separate tab'
        'second' = '2. Paste the conversation'
        'secondDetail' = 'The new request and relevant messages'
        'third' = '3. Review the result'
        'reply' = 'Customer reply'
        'tip' = 'Manager suggestion'
        'footer' = 'The manager sends the customer reply.'
    }
}
foreach ($locale in $tours.Keys) {
    $copy = $tours[$locale]
    $bitmap = [System.Drawing.Bitmap]::new(1188, 616)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $graphics.Clear([System.Drawing.ColorTranslator]::FromHtml('#F5F7F9'))
    Draw-ChatIcon $graphics 50 42 75
    Draw-Label $graphics $copy.title 38 148 36 '#263347' $true
    Draw-Label $graphics $copy.subtitle 23 150 87 '#647184'
    $white = New-Brush '#FFFFFF'
    $green = New-Brush '#166A5C'
    $gold = New-Brush '#DEA45C'
    $light = New-Brush '#DEE5EA'
    $graphics.FillRectangle($white, 50, 173, 1088, 120)
    Draw-Label $graphics $copy.first 27 75 191 '#166A5C' $true
    Draw-Label $graphics $copy.firstDetail 23 75 240 '#263347'
    $graphics.FillRectangle($white, 50, 310, 510, 205)
    Draw-Label $graphics $copy.second 27 75 328 '#166A5C' $true
    Draw-Label $graphics $copy.secondDetail 20 75 376 '#263347'
    $graphics.FillRectangle($light, 75, 430, 340, 12)
    $graphics.FillRectangle($light, 75, 456, 415, 12)
    $graphics.FillRectangle($white, 582, 310, 556, 205)
    Draw-Label $graphics $copy.third 27 607 328 '#166A5C' $true
    $graphics.FillRectangle($green, 607, 381, 5, 41)
    Draw-Label $graphics $copy.reply 23 627 384 '#263347'
    $graphics.FillRectangle($gold, 607, 447, 5, 41)
    Draw-Label $graphics $copy.tip 23 627 450 '#263347'
    Draw-Label $graphics $copy.footer 22 50 551 '#647184'
    $bitmap.Save((Join-Path $assetDirectory ('tour_' + $locale + '.png')), [System.Drawing.Imaging.ImageFormat]::Png)
    $white.Dispose(); $green.Dispose(); $gold.Dispose(); $light.Dispose()
    $graphics.Dispose(); $bitmap.Dispose()
}
Write-Output 'Generated five logos and two tour images.'
