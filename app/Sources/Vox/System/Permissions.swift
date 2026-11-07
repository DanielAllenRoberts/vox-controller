import AVFoundation
import AppKit
import ApplicationServices
import CoreGraphics
import EventKit
import Observation

/// The macOS privacy permissions Vox needs. Checked without prompting; requested only on a button
/// press. Vox.app asks for them itself, because the engine it launches inherits them. A Python
/// child of an app that never asked for the microphone records pure silence, with no error.
@MainActor
@Observable
final class Permissions {
    enum Kind: String, CaseIterable, Identifiable {
        case microphone, accessibility, screenRecording, calendar
        var id: String { rawValue }

        var title: String {
            switch self {
            case .microphone: "Microphone"
            case .accessibility: "Accessibility"
            case .screenRecording: "Screen Recording"
            case .calendar: "Calendar"
            }
        }

        var symbol: String {
            switch self {
            case .microphone: "mic.fill"
            case .accessibility: "accessibility"
            case .screenRecording: "rectangle.dashed.badge.record"
            case .calendar: "calendar"
            }
        }

        var why: String {
            switch self {
            case .microphone: "So Vox can hear you. Audio is processed on this Mac."
            case .accessibility: "So Vox can click, type and read what's on screen when you ask it to."
            case .screenRecording: "Optional. Lets Vox look at the screen when you ask \"what's this?\""
            case .calendar: "Lets routines and questions like \"what's on today?\" read your calendars."
            }
        }

        var required: Bool { self == .microphone || self == .accessibility }

        var settingsURL: URL {
            let anchor = switch self {
            case .microphone: "Privacy_Microphone"
            case .accessibility: "Privacy_Accessibility"
            case .screenRecording: "Privacy_ScreenCapture"
            case .calendar: "Privacy_Calendars"
            }
            return URL(string: "x-apple.systempreferences:com.apple.preference.security?\(anchor)")!
        }
    }

    enum Status { case granted, denied, notAsked }

    private(set) var statuses: [Kind: Status] = [:]
    /// Kinds the user has already pressed Allow for (drives "still not working?" help).
    private(set) var asked: Set<Kind> = []
    private var pollTask: Task<Void, Never>?

    init() { refresh() }

    func refresh() {
        var s: [Kind: Status] = [:]
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: s[.microphone] = .granted
        case .notDetermined: s[.microphone] = .notAsked
        default: s[.microphone] = .denied
        }
        s[.accessibility] = AXIsProcessTrusted() ? .granted : .notAsked
        s[.screenRecording] = CGPreflightScreenCaptureAccess() ? .granted : .notAsked
        switch EKEventStore.authorizationStatus(for: .event) {
        case .fullAccess: s[.calendar] = .granted
        case .notDetermined: s[.calendar] = .notAsked
        default: s[.calendar] = .denied
        }
        if s != statuses { statuses = s }
    }

    func status(_ k: Kind) -> Status { statuses[k] ?? .notAsked }
    var requiredGranted: Bool { Kind.allCases.filter(\.required).allSatisfy { status($0) == .granted } }

    /// Ask the way every Mac app does: the FIRST press shows macOS's own prompt, whose "Open System
    /// Settings" button takes the user to the right pane. Only a repeat press (the prompt was dismissed
    /// or macOS won't show it again) opens System Settings directly. Doing both at once, as an earlier
    /// version did, put the prompt and the Settings window on screen together.
    func request(_ k: Kind) {
        let again = asked.contains(k)
        asked.insert(k)
        switch k {
        case .microphone:
            if status(.microphone) == .denied {
                NSWorkspace.shared.open(k.settingsURL)   // macOS never re-prompts once denied
            } else {
                AVCaptureDevice.requestAccess(for: .audio) { _ in Task { @MainActor in self.refresh() } }
            }
        case .accessibility:
            if again {
                NSWorkspace.shared.open(k.settingsURL)
            } else {
                let opts = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
                _ = AXIsProcessTrustedWithOptions(opts)
            }
            watch()
        case .screenRecording:
            if again {
                NSWorkspace.shared.open(k.settingsURL)
            } else {
                _ = CGRequestScreenCaptureAccess()   // shows the system prompt the first time
            }
            watch()
        case .calendar:
            if status(.calendar) == .denied {
                NSWorkspace.shared.open(k.settingsURL)   // macOS never re-prompts once denied
            } else {
                EKEventStore().requestFullAccessToEvents { _, _ in Task { @MainActor in self.refresh() } }
            }
        }
    }

    /// Accessibility and Screen Recording are granted in System Settings with no callback, so poll
    /// for a minute after sending the user there.
    private func watch() {
        pollTask?.cancel()
        pollTask = Task {
            for _ in 0..<60 {
                try? await Task.sleep(for: .seconds(1))
                refresh()
            }
        }
    }
}
