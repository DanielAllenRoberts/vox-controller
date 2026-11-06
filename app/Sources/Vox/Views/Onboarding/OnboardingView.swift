import SwiftUI

/// First run: from a downloaded app to a working voice assistant, without a terminal.
///
/// The engine install starts the moment the user presses Get Started and runs while they grant
/// permissions, so by the time they reach the Engine step it's usually done. Screen Recording isn't
/// asked for here; it's optional and Settings → Permissions offers it when wanted.
struct OnboardingView: View {
    enum Step: Int, CaseIterable { case welcome, microphone, accessibility, engine, brain, tryIt, done }

    @Environment(AppModel.self) private var model
    @Environment(\.dismissWindow) private var dismissWindow
    @Environment(\.openWindow) private var openWindow
    @State var step: Step = .welcome
    @State private var perms = Permissions()
    @State private var installer = Installer()
    @State private var brainReady = false

    var body: some View {
        VStack(spacing: 0) {
            StepDots(current: step.rawValue, count: Step.allCases.count)
                .padding(.top, 22)
            Group {
                switch step {
                case .welcome: WelcomeStep()
                case .microphone: PermissionStep(kind: .microphone, perms: perms)
                case .accessibility: PermissionStep(kind: .accessibility, perms: perms)
                case .engine: EngineStep(installer: installer)
                case .brain: BrainStep(ready: $brainReady)
                case .tryIt: TryItStep()
                case .done: DoneStep()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .padding(.horizontal, 56)
            .transition(.asymmetric(insertion: .move(edge: .trailing).combined(with: .opacity),
                                    removal: .move(edge: .leading).combined(with: .opacity)))
            .id(step)
            Divider()
            footer.padding(.horizontal, 20).padding(.vertical, 14)
        }
        .frame(width: 640, height: 620)
        .onAppear { perms.refresh() }
        .onChange(of: step) { _, s in if s == .engine { startEngine() } }
    }

    private var footer: some View {
        HStack {
            if step != .welcome && step != .done {
                Button("Back") { go(-1) }.keyboardShortcut(.cancelAction)
            }
            Spacer()
            if let skip = skipLabel { Button(skip) { go(1) } }
            Button(primaryLabel) { primary() }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
                .disabled(!canContinue)
        }
        .controlSize(.large)
    }

    private var primaryLabel: String {
        switch step {
        case .welcome: "Get Started"
        case .done: "Open Vox"
        default: "Continue"
        }
    }

    private var skipLabel: String? {
        switch step {
        case .brain where !brainReady: "Set Up Later"
        case .accessibility where perms.status(.accessibility) != .granted: "Skip for Now"
        case .tryIt: "Skip"
        default: nil
        }
    }

    private var canContinue: Bool {
        switch step {
        case .microphone: perms.status(.microphone) == .granted
        case .accessibility: perms.status(.accessibility) == .granted
        case .engine: model.engine.isRunning
        case .brain: brainReady
        default: true
        }
    }

    private func primary() {
        switch step {
        case .welcome:
            beginEngineInBackground()
            go(1)
        case .done:
            model.onboardingDone = true
            openWindow(id: "main")
            dismissWindow(id: "onboarding")
        default:
            go(1)
        }
    }

    private func go(_ delta: Int) {
        guard let next = Step(rawValue: step.rawValue + delta) else { return }
        withAnimation(.smooth(duration: 0.35)) { step = next }
    }

    /// Install (if needed) while the user handles permissions. The engine itself only starts once
    /// they've reached the Engine step: started before the microphone was allowed, it would open
    /// the mic too early and record silence until restarted.
    private func beginEngineInBackground() {
        let loc = model.engine.location
        guard !loc.isReady else { return }
        Task {
            await installer.install(into: loc)
            model.engine.refreshLocation()
            if step.rawValue >= Step.engine.rawValue { startEngine() }
        }
    }

    private func startEngine() {
        if model.engine.location.isReady { model.boot() }
    }
}

// MARK: Pieces

private struct StepDots: View {
    var current: Int
    var count: Int
    var body: some View {
        HStack(spacing: 7) {
            ForEach(0..<count, id: \.self) { i in
                Capsule()
                    .fill(i == current ? Color.accentColor : Color.secondary.opacity(i < current ? 0.55 : 0.22))
                    .frame(width: i == current ? 20 : 7, height: 7)
            }
        }
        .animation(.smooth, value: current)
    }
}

/// The shared layout of every step: symbol, title, explanation, then the step's own controls.
private struct StepLayout<Content: View>: View {
    var symbol: String
    var tint: Color = .accentColor
    var title: String
    var message: String
    /// For steps with a lot of controls: a smaller symbol and title leave room for them.
    var compact = false
    @ViewBuilder var content: Content

    var body: some View {
        VStack(spacing: compact ? 12 : 18) {
            Spacer(minLength: compact ? 4 : 10)
            ZStack {
                Circle().fill(tint.opacity(0.14)).frame(width: compact ? 56 : 84, height: compact ? 56 : 84)
                Image(systemName: symbol).font(.system(size: compact ? 24 : 36, weight: .medium)).foregroundStyle(tint)
            }
            VStack(spacing: compact ? 4 : 8) {
                Text(title).font((compact ? Font.title : .largeTitle).weight(.semibold)).multilineTextAlignment(.center)
                Text(message).font(.title3).foregroundStyle(.secondary)
                    .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
            }
            content.frame(maxWidth: 460)
            Spacer(minLength: 10)
        }
    }
}

private struct WelcomeStep: View {
    var body: some View {
        StepLayout(symbol: "waveform", title: "Welcome to Vox",
                   message: "Control your Mac with your voice. Open apps, click buttons, dictate, ask questions, all hands-free.") {
            VStack(alignment: .leading, spacing: 10) {
                Bullet(symbol: "lock.shield", text: "Listening and speech recognition happen on this Mac.")
                Bullet(symbol: "clock", text: "Setup takes about five minutes. Vox installs what it needs while you go.")
                Bullet(symbol: "menubar.rectangle", text: "Afterwards Vox lives quietly in your menu bar.")
            }
            .padding(.top, 6)
        }
    }
}

private struct Bullet: View {
    var symbol: String
    var text: String
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Image(systemName: symbol).foregroundStyle(Color.accentColor).frame(width: 20)
            Text(text).foregroundStyle(.secondary)
        }
    }
}

private struct PermissionStep: View {
    var kind: Permissions.Kind
    var perms: Permissions
    @State private var askedAt: Date?

    var body: some View {
        let granted = perms.status(kind) == .granted
        StepLayout(symbol: granted ? "checkmark.circle.fill" : kind.symbol, tint: granted ? .green : .accentColor,
                   title: granted ? "\(kind.title) allowed" : "Allow \(kind.title)",
                   message: kind.why) {
            if !granted {
                VStack(spacing: 10) {
                    Button(perms.status(kind) == .denied ? "Open System Settings" : "Allow \(kind.title)…") {
                        perms.request(kind)
                        askedAt = Date()
                    }
                    .controlSize(.large)
                    if kind == .accessibility {
                        Text("macOS opens System Settings. Turn on **Vox** in the list, then come back here.")
                            .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    } else if perms.status(kind) == .denied {
                        Text("Microphone access was turned off earlier. Turn on **Vox** in System Settings → Privacy & Security → Microphone.")
                            .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    }
                    if askedAt != nil && kind == .accessibility {
                        // Seen in practice: Vox is switched on in System Settings but this process
                        // still isn't trusted (an older build's entry, or a grant macOS only applies
                        // on relaunch). Never leave the user stuck on this screen.
                        Text("Already switched on and this still says no? Quit Vox and open it again. If that doesn't work, remove Vox from the list with \u{2212} and add it back.")
                            .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)
                            .padding(.top, 6)
                    }
                }
            }
        }
        // Check every second while this step is on screen. Permission changes in System Settings
        // send no notification, and an earlier 60-second window left people stuck here.
        .task {
            while !Task.isCancelled {
                perms.refresh()
                try? await Task.sleep(for: .seconds(1))
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            perms.refresh()
        }
    }
}

private struct EngineStep: View {
    @Environment(AppModel.self) private var model
    var installer: Installer
    @State private var showDetails = false

    var body: some View {
        let running = model.engine.isRunning
        StepLayout(symbol: running ? "checkmark.circle.fill" : "shippingbox", tint: running ? .green : .accentColor,
                   title: running ? "Vox is ready" : "Getting Vox ready",
                   message: running ? "The speech engine is running." : subtitle) {
            VStack(spacing: 12) {
                switch installer.phase {
                case .running:
                    ProgressView(value: installer.progress).frame(maxWidth: 360)
                    Text(installer.step).font(.callout).foregroundStyle(.secondary)
                case .failed(let why):
                    Label(why, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red).font(.callout)
                    Button("Try Again") { Task { await installer.install(into: model.engine.location); model.engine.refreshLocation(); model.engine.start() } }
                default:
                    if !running {
                        if case .failed(let why) = model.engine.state {
                            Text(why).font(.callout).foregroundStyle(.red).multilineTextAlignment(.center)
                            Button("Try Again") { model.engine.start() }
                        } else {
                            ProgressView().controlSize(.small)
                            Text("Loading speech models. The first start can take a minute.").font(.callout).foregroundStyle(.secondary)
                        }
                    }
                }
                if !installer.lines.isEmpty {
                    DisclosureGroup("Details", isExpanded: $showDetails) {
                        ScrollView {
                            Text(installer.lines.suffix(80).joined(separator: "\n"))
                                .font(.caption.monospaced()).foregroundStyle(.secondary)
                                .frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled)
                        }
                        .frame(height: 110)
                    }
                    .frame(maxWidth: 420)
                }
            }
        }
    }

    private var subtitle: String {
        model.engine.location.kind == .checkout
            ? "Starting the engine from your source checkout."
            : "Installing a private copy of Python and the speech libraries. Nothing else on your Mac is changed."
    }
}

// MARK: Brain

private struct BrainStep: View {
    @Environment(AppModel.self) private var model
    @Binding var ready: Bool
    @State private var choice: BrainPreset = .current
    @State private var keys: [String: Bool] = [:]
    @State private var test: TestState = .idle
    @State private var claudeLoggedIn: Bool?

    enum TestState: Equatable { case idle, testing, passed(Int), failed(String) }

    var body: some View {
        StepLayout(symbol: "brain", title: "Choose a brain",
                   message: "Vox recognises commands on its own. A language model handles everything else.", compact: true) {
            VStack(spacing: 8) {
                ForEach(BrainPreset.allCases) { p in
                    PresetRow(preset: p, selected: choice == p, keys: keys, claudeLoggedIn: claudeLoggedIn) {
                        choice = p; test = .idle; ready = false
                    }
                }
                ForEach(choice.keysNeeded, id: \.self) { name in KeyField(name: name, isSet: keys[name] ?? false) { await refreshKeys() } }
                HStack {
                    testStatus
                    Spacer()
                    Button(choice == .current ? "Test" : "Use This") { Task { await apply() } }
                        .disabled(test == .testing || !model.engine.isRunning || choice.keysNeeded.contains { !(keys[$0] ?? false) })
                }
                .padding(.top, 4)
            }
        }
        .task { await refreshKeys(); claudeLoggedIn = await ClaudeCLI.loggedIn() }
    }

    @ViewBuilder private var testStatus: some View {
        switch test {
        case .idle: Text(model.engine.isRunning ? " " : "Waiting for the engine…").font(.callout).foregroundStyle(.secondary)
        case .testing: HStack(spacing: 6) { ProgressView().controlSize(.small); Text("Testing…").foregroundStyle(.secondary) }
        case .passed(let ms): Label("Working. Replied in \(String(format: "%.1f", Double(ms) / 1000)) s", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
        case .failed(let why): Label(why, systemImage: "xmark.octagon.fill").foregroundStyle(.red).lineLimit(2).font(.callout)
        }
    }

    private func refreshKeys() async {
        if let k: [String: Bool] = try? await model.api.get("secrets") { keys = k }
    }

    private func apply() async {
        test = .testing
        if let p = choice.settings {
            for (k, v) in p { try? await model.api.setSetting(k, .string(v)) }
            // Provider changes apply on restart.
            model.engine.restart()
            for _ in 0..<120 where !model.engine.isRunning { try? await Task.sleep(for: .milliseconds(500)) }
            await model.reloadSettings()
        }
        struct R: Decodable { var ok: Bool; var reply: String; var ms: Int }
        do {
            let r: R = try await model.api.send("brain/test", method: "POST", body: ["brain": "small"])
            test = r.ok ? .passed(r.ms) : .failed(r.reply)
            ready = r.ok
        } catch {
            test = .failed(error.localizedDescription)
        }
    }
}

enum BrainPreset: String, CaseIterable, Identifiable {
    case current, fast, anthropic, subscription
    var id: String { rawValue }

    var title: String {
        switch self {
        case .current: "Keep my current setup"
        case .fast: "Fast and cheap"
        case .anthropic: "Claude via API"
        case .subscription: "Claude subscription"
        }
    }

    var detail: String {
        switch self {
        case .current: "Use the brains already configured."
        case .fast: "DeepSeek for everyday replies (about 1 s, fractions of a cent), Claude for hard ones."
        case .anthropic: "Claude Haiku for everyday replies, Sonnet for hard ones. Pay per use."
        case .subscription: "Uses your Claude Pro or Max plan. No per-use cost, but slower (2–5 s)."
        }
    }

    var keysNeeded: [String] {
        switch self {
        case .fast: ["DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY"]
        case .anthropic: ["ANTHROPIC_API_KEY"]
        default: []
        }
    }

    var settings: [String: String]? {
        switch self {
        case .current: nil
        case .fast: ["small_brain_provider": "openai", "small_brain_model": "deepseek-v4-flash",
                     "big_brain_provider": "anthropic", "big_brain_model": "claude-sonnet-4-6"]
        case .anthropic: ["small_brain_provider": "anthropic", "small_brain_model": "claude-haiku-4-5-20251001",
                          "big_brain_provider": "anthropic", "big_brain_model": "claude-sonnet-4-6"]
        case .subscription: ["small_brain_provider": "claude_sdk", "small_brain_model": "claude-haiku-4-5-20251001",
                             "big_brain_provider": "claude_sdk", "big_brain_model": "claude-sonnet-4-6"]
        }
    }
}

private struct PresetRow: View {
    var preset: BrainPreset
    var selected: Bool
    var keys: [String: Bool]
    var claudeLoggedIn: Bool?
    var select: () -> Void

    var body: some View {
        Button(action: select) {
            HStack(spacing: 12) {
                Image(systemName: selected ? "largecircle.fill.circle" : "circle")
                    .foregroundStyle(selected ? Color.accentColor : Color.secondary).font(.title3)
                VStack(alignment: .leading, spacing: 2) {
                    Text(preset.title).font(.body.weight(.medium))
                    Text(preset.detail).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    if preset == .subscription, claudeLoggedIn == false {
                        Text("Needs Claude Code signed in. Install it from claude.com/code, then run `claude` once.")
                            .font(.caption).foregroundStyle(.orange)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(10)
            .contentShape(Rectangle())
            .background(selected ? Color.accentColor.opacity(0.08) : .clear, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous)
                .strokeBorder(selected ? Color.accentColor.opacity(0.5) : Color.secondary.opacity(0.2)))
        }
        .buttonStyle(.plain)
    }
}

private struct KeyField: View {
    @Environment(AppModel.self) private var model
    var name: String
    var isSet: Bool
    var saved: () async -> Void
    @State private var value = ""
    @State private var error: String?

    private var label: String {
        switch name {
        case "DEEPSEEK_API_KEY": "DeepSeek API key"
        case "ANTHROPIC_API_KEY": "Anthropic API key"
        default: name
        }
    }

    var body: some View {
        HStack {
            if isSet {
                Label("\(label) saved", systemImage: "key.fill").foregroundStyle(.green).font(.callout)
                Spacer()
            } else {
                SecureField(label, text: $value).textFieldStyle(.roundedBorder)
                Button("Save") {
                    Task {
                        do { try await model.api.post("secrets", ["name": .string(name), "value": .string(value)]); value = ""; await saved() }
                        catch { self.error = error.localizedDescription }
                    }
                }
                .disabled(value.count < 8)
            }
        }
        .help(error ?? "Saved to Vox's private settings file on this Mac, readable only by you.")
    }
}

/// Is the Claude Code CLI installed and signed in? (Needed for the subscription brain.) Reads
/// only the `loggedIn` flag: the full output includes the account email, which isn't shown or kept.
enum ClaudeCLI {
    static func loggedIn() async -> Bool? {
        await Task.detached { () -> Bool? in
            guard let bin = EngineLocation.childPATH.split(separator: ":")
                .map({ URL(fileURLWithPath: String($0)).appending(path: "claude") })
                .first(where: { FileManager.default.isExecutableFile(atPath: $0.path) }) else { return false }
            let p = Process()
            p.executableURL = bin
            p.arguments = ["auth", "status", "--json"]
            let out = Pipe()
            p.standardOutput = out
            p.standardError = Pipe()
            guard (try? p.run()) != nil else { return nil }
            p.waitUntilExit()
            let data = out.fileHandleForReading.readDataToEndOfFile()
            let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            return json?["loggedIn"] as? Bool
        }.value
    }
}

// MARK: Try it + done

private struct TryItStep: View {
    @Environment(AppModel.self) private var model
    @State private var startCount = 0
    @State private var heard: String?

    var body: some View {
        StepLayout(symbol: heard == nil ? "mic.and.signal.meter" : "checkmark.circle.fill",
                   tint: heard == nil ? .accentColor : .green,
                   title: heard == nil ? "Say hello" : "Vox heard you",
                   message: heard == nil ? "Say \u{201C}Hey Vox, what time is it?\u{201D}" : "\u{201C}\(heard!)\u{201D}") {
            VStack(spacing: 10) {
                if heard == nil {
                    HStack(spacing: 8) { ProgressView().controlSize(.small); Text("Listening…").foregroundStyle(.secondary) }
                    Text("Can't talk right now? Type instead:").font(.callout).foregroundStyle(.secondary).padding(.top, 8)
                    AskField(compact: true)
                } else if let reply = model.turns.last(where: { !$0.isUser }), model.turns.count > startCount + 1 {
                    Text(reply.text).font(.callout).padding(10).frame(maxWidth: .infinity)
                        .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 10))
                }
            }
        }
        .onAppear { startCount = model.turns.count }
        .onChange(of: model.turns.count) { _, _ in
            if model.turns.count > startCount, let u = model.turns.suffix(from: startCount).first(where: \.isUser) {
                withAnimation { heard = u.text }
            }
        }
    }
}

private struct DoneStep: View {
    var body: some View {
        StepLayout(symbol: "checkmark.seal.fill", tint: .green, title: "You're all set",
                   message: "Vox is listening. Find it in your menu bar any time.") {
            VStack(alignment: .leading, spacing: 10) {
                Bullet(symbol: "command", text: "\u{201C}Take control\u{201D} to give commands. \u{201C}Stand down\u{201D} to stop.")
                Bullet(symbol: "bubble.left", text: "\u{201C}Hey Vox\u{201D} to ask a question or chat.")
                Bullet(symbol: "keyboard", text: "\u{201C}Start typing\u{201D} to dictate into any text field.")
            }
        }
    }
}
