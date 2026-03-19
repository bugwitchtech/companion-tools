; ============================================
; Unified Listener Injector for Claude Desktop
; Watches for trigger files from the unified listener
; and injects messages into Claude Desktop window
; Supports: Text messages, image pasting, Discord + Telegram
;
; HOLD MECHANISM: Flag-based cooldown after injection.
; After injecting a message, waits COOLDOWN_SECONDS before
; allowing the next injection. Simple, reliable, no pixel detection.
; ============================================

#Persistent
#SingleInstance Force
SetTitleMatchMode, 2

; ============================================================
; CONFIG
; ============================================================
global BRIDGE_DIR := A_ScriptDir
global COOLDOWN_SECONDS := 45
; ============================================================

global FLAG_FILE := BRIDGE_DIR . "\listener_flag.txt"
global INCOMING_FILE := BRIDGE_DIR . "\listener_incoming.txt"
global BUSY_FILE := BRIDGE_DIR . "\busy.txt"
global CLIPBOARD_SCRIPT := BRIDGE_DIR . "\copy_image_to_clipboard.ps1"
global PAUSE_FILE := BRIDGE_DIR . "\pause.txt"
global CHECK_INTERVAL := 2000
global DESKTOP_TITLE := "Claude"
global LastInjectTime := 0

; === STARTUP ===
TrayTip, Unified Listener, Injector started - watching for messages, 3
SetTimer, CheckForMessage, %CHECK_INTERVAL%
return

; === HOLD MECHANISM ===
; Simple cooldown: after injecting, wait COOLDOWN_SECONDS before next injection.
; This gives Claude time to process and respond before the next message arrives.
IsInCooldown() {
    global LastInjectTime, COOLDOWN_SECONDS
    if (LastInjectTime = 0) {
        return false
    }
    elapsed := A_TickCount - LastInjectTime
    elapsedSec := elapsed // 1000
    remaining := COOLDOWN_SECONDS - elapsedSec
    if (remaining > 0) {
        return true
    }
    return false
}

GetCooldownRemaining() {
    global LastInjectTime, COOLDOWN_SECONDS
    elapsed := A_TickCount - LastInjectTime
    elapsedSec := elapsed // 1000
    remaining := COOLDOWN_SECONDS - elapsedSec
    if (remaining < 0) {
        remaining := 0
    }
    return remaining
}

; === MAIN CHECK ROUTINE ===
CheckForMessage:
    if !FileExist(FLAG_FILE) {
        return
    }

    FileRead, messageText, %INCOMING_FILE%
    if (ErrorLevel || messageText = "") {
        FileDelete, %FLAG_FILE%
        return
    }

    ; === COOLDOWN HOLD ===
    ; Wait if we recently injected a message
    while (IsInCooldown()) {
        remaining := GetCooldownRemaining()
        if (Mod(remaining, 10) = 0 && remaining > 0) {
            TrayTip, Unified Listener, Holding message - cooldown %remaining%s remaining, 1
        }
        Sleep, 1000
    }

    ; === ROUTE MESSAGE ===
    if (SubStr(messageText, 1, 7) = "[Photo:" || SubStr(messageText, 1, 7) = "[Image:") {
        closeBracket := InStr(messageText, "]")
        if (closeBracket > 0) {
            pathStart := InStr(messageText, ": ") + 2
            imagePath := SubStr(messageText, pathStart, closeBracket - pathStart)
            caption := ""
            if (StrLen(messageText) > closeBracket + 1) {
                caption := SubStr(messageText, closeBracket + 2)
                caption := Trim(caption)
            }
            success := InjectPhoto(imagePath, caption)
        } else {
            success := false
        }
    } else {
        success := InjectMessage(messageText)
    }

    ; Clean up flag files
    FileDelete, %FLAG_FILE%
    FileDelete, %INCOMING_FILE%

    if (success) {
        ; Start cooldown timer
        LastInjectTime := A_TickCount
        TrayTip, Unified Listener, Message injected! Cooldown %COOLDOWN_SECONDS%s, 1
    } else {
        TrayTip, Unified Listener, Failed to inject - check Desktop, 2
    }
return

; === TEXT INJECTION ===
InjectMessage(text) {
    WinGet, hwnd, ID, %DESKTOP_TITLE%
    if (!hwnd) {
        WinGet, hwnd, ID, Anthropic
        if (!hwnd) {
            return false
        }
    }

    WinActivate, ahk_id %hwnd%
    WinWaitActive, ahk_id %hwnd%, , 3
    if (ErrorLevel) {
        return false
    }

    Sleep, 200
    WinGetPos, X, Y, W, H, ahk_id %hwnd%
    inputX := W / 2
    inputY := H - 100
    Click, %inputX%, %inputY%
    Sleep, 100

    fullMessage := text
    SendInput, {Raw}%fullMessage%
    Sleep, 100
    SendInput, ^{Enter}
    return true
}

; === PHOTO INJECTION ===
InjectPhoto(imagePath, caption) {
    if !FileExist(imagePath) {
        TrayTip, Unified Listener, Image not found: %imagePath%, 2
        return false
    }

    WinGet, hwnd, ID, %DESKTOP_TITLE%
    if (!hwnd) {
        WinGet, hwnd, ID, Anthropic
        if (!hwnd) {
            return false
        }
    }

    RunWait, powershell -ExecutionPolicy Bypass -File "%CLIPBOARD_SCRIPT%" "%imagePath%", , Hide
    if (ErrorLevel) {
        TrayTip, Unified Listener, Failed to copy image, 2
        return false
    }

    Sleep, 300
    WinActivate, ahk_id %hwnd%
    WinWaitActive, ahk_id %hwnd%, , 3
    if (ErrorLevel) {
        return false
    }

    Sleep, 200
    WinGetPos, X, Y, W, H, ahk_id %hwnd%
    inputX := W / 2
    inputY := H - 100
    Click, %inputX%, %inputY%
    Sleep, 100

    SendInput, ^v
    Sleep, 4000
    Click, %inputX%, %inputY%
    Sleep, 300

    if (caption != "") {
        SendInput, {Raw}%caption%
        Sleep, 300
    } else {
        SendInput, {Raw}[Photo]
        Sleep, 300
    }

    Sleep, 200
    SendInput, ^{Enter}
    return true
}

; === HOTKEYS ===

; F9 = Toggle Pause
F9::
    if FileExist(PAUSE_FILE) {
        FileDelete, %PAUSE_FILE%
        TrayTip, Unified Listener, RESUMED, 2
    } else {
        FileAppend, paused, %PAUSE_FILE%
        TrayTip, Unified Listener, PAUSED, 2
    }
return

; F10 = Manual trigger
F10::
    if FileExist(FLAG_FILE) {
        Gosub, CheckForMessage
    } else {
        MsgBox, No message waiting
    }
return

; F11 = Status
F11::
    remaining := GetCooldownRemaining()
    status := "Unified Listener Status`n"
    status .= "========================`n"
    status .= "Flag File: " . (FileExist(FLAG_FILE) ? "EXISTS" : "none") . "`n"
    WinGet, hwnd, ID, %DESKTOP_TITLE%
    status .= "Window: " . (hwnd ? "FOUND" : "not found") . "`n"
    status .= "Cooldown: " . (IsInCooldown() ? remaining . "s remaining" : "clear") . "`n"
    MsgBox, %status%
return

; F12 = Exit
F12::
    TrayTip, Unified Listener, Shutting down, 1
    Sleep, 1000
    ExitApp
return
