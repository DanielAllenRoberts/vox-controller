import AVFoundation
import AppKit
import ApplicationServices
import CoreGraphics
import Observation

/// The macOS privacy permissions Vox needs. Checked without prompting; requested only on a button
/// press. Vox.app asks for them itself, because the engine it launches inherits them. A Python
/// child of an app that never asked for the microphone records pure silence, with no error.
@MainActor
@Observable
final class Permissions {
    enum Kind: String, CaseIterable, Identifiable {
        case microphone, accessibility, screenRecording
        var id: String { rawValue }

        var title: String {
            switch self {
            case .microphone: "Microphone"
            case .accessibility: "Accessibility"
            case .screenRecording: "Screen Recording"
            }
        }

        var symbol: String {
            switch self {
            case .microphone: "mic.fill"
            case .accessibility: "accessibility"
            case .screenRecording: "rectangle.dashed.badge.record"
            }
        }

        var why: String {
            switch self {
            case .microphone: "So Vox can hear you. Audio is processed on this Mac."
            case .accessibility: "So Vox can click, type and read what's on screen when you ask it to."
            case .screenRecording: "Optional. Lets Vox look at the screen when you ask \"what's this?\""
            }
        }

        var required: Bool { self != .screenRecording }

        var settingsURL: URL {
            let anchor = switch self {
            case .microphone: "Privacy_Microphone"
            case .accessibility: "Privacy_Accessibility"
            case .screenRecording: "Privacy_ScreenCapture"
            }
            return URL(string: "x-apple.systempreferences:com.apple.preference.security?\(anchor)")!
        }
    }

    enum Status { case granted, denied, notAsked }

    private(set) var statuses: [Kind: Status] = [:]
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
        if s != statuses { statuses = s }
    }

    func status(_ k: Kind) -> Status { statuses[k] ?? .notAsked }
    var requiredGranted: Bool { Kind.allCases.filter(\.required).allSatisfy { status($0) == .granted } }

    func request(_ k: Kind) {
        switch k {
        case .microphone:
            if status(.microphone) == .denied {
                NSWorkspace.shared.open(k.settingsURL)   // macOS never re-prompts once denied
            } else {
                AVCaptureDevice.requestAccess(for: .audio) { _ in Task { @MainActor in self.refresh() } }
            }
        case .accessibility:
            let opts = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
            _ = AXIsProcessTrustedWithOptions(opts)
            NSWorkspace.shared.open(k.settingsURL)
            watch()
        case .screenRecording:
            if !CGRequestScreenCaptureAccess() { NSWorkspace.shared.open(k.settingsURL) }
            watch()
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
