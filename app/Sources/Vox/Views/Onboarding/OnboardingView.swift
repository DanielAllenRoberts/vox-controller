import SwiftUI

/// First run: from a downloaded app to a working voice assistant, without a terminal.
///
/// The engine install starts the moment the user presses Get Started and runs while they grant
/// permissions, so by the time they reach the Engine step it's usually done. Screen Recording isn't
/// asked for here; it's optional and Settings → Permissions offers it when wanted.
struct OnboardingView: View {
    enum Step: Int, CaseIterable { case welcome, microphone, accessibility, engine, micCheck, brain, voice, connections, aboutYou, tryIt, done }

    @Environment(AppModel.self) private var model
    @Environment(\.dismissWindow) private var dismissWindow
    @Environment(\.openWindow) private var openWindow
    @State var step: Step = .welcome
    @State private var perms = Permissions()
    @State private var installer = Installer()
    @State private var brain = BrainSetup()
    @State var aboutYou = AboutYouSetup()
    /// `--snapshot` only: a fixed mic reading, since no engine is polled there.
    var meterPreview: MicLevel?
    @State private var heardSpeech = false
    @State private var tryItSince = Date()

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
                case .micCheck: MicCheckStep(heard: $heardSpeech, preview: meterPreview)
                case .brain: BrainStep(setup: brain)
                case .voice: VoiceStep()
                case .connections: ConnectionsStep(perms: perms)
                case .aboutYou: AboutYouStep(setup: aboutYou)
                case .tryIt: TryItStep(perms: perms, meterPreview: meterPreview)
                case .done: DoneStep(perms: perms)
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
        .onChange(of: step) { _, s in
            if s == .engine { startEngine() }
            if s == .tryIt { tryItSince = Date() }
        }
    }

    /// Fixed-width buttons, kept out of the step animation: when the label changed ("Get Started" →
    /// "Continue") the width animated with the page slide and the hover highlight drew at the wrong
    /// size.
    private var footer: some View {
        HStack(spacing: 10) {
            if step != .welcome && step != .done {
                Button { go(-1) } label: { Text("Back").frame(minWidth: 70) }
                    .keyboardShortcut(.cancelAction)
            }
            Spacer()
            if let skip = skipLabel {
                Button { go(1) } label: { Text(skip).frame(minWidth: 110) }
            }
            Button { primary() } label: { Text(primaryLabel).frame(minWidth: 110) }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
                .disabled(!canContinue)
        }
        .controlSize(.large)
        .transaction { $0.animation = nil }
    }

    // The blue button is never a dead end: on every step it does the next useful thing (ask for the
    // permission, test the brain, move on), and a Skip sits beside anything that can stall.
    // An earlier version disabled Continue until a condition was met that the screen didn't explain
    // (press Test, wait for a permission check), and people got stuck.

    private var primaryLabel: String {
        switch step {
        case .welcome: "Get Started"
        case .microphone where perms.status(.microphone) == .denied: "Open Settings"
        case .microphone where perms.status(.microphone) != .granted: "Allow Microphone"
        case .accessibility where perms.status(.accessibility) != .granted: "Allow Access…"
        case .brain where brain.isTesting: "Testing…"
        case .tryIt where !model.turns.contains(where: { $0.isUser && ($0.date ?? .distantPast) > tryItSince }): "Skip"
        case .done: "Open Vox"
        default: "Continue"
        }
    }

    private var skipLabel: String? {
        switch step {
        case .microphone where perms.status(.microphone) != .granted: "Skip for Now"
        case .accessibility where perms.status(.accessibility) != .granted: "Skip for Now"
        case .engine where !model.engine.isRunning: "Skip for Now"
        case .micCheck where !heardSpeech: "Skip"
        case .brain where !brain.passed: "Set Up Later"
        case .aboutYou: "Skip"
        case .connections: "Skip"
        default: nil
        }
    }

    private var canContinue: Bool {
        !(step == .brain && brain.isTesting)
    }

    private func primary() {
        switch step {
        case .welcome:
            beginEngineInBackground()
            go(1)
        case .microphone where perms.status(.microphone) != .granted:
            perms.request(.microphone)
        case .accessibility where perms.status(.accessibility) != .granted:
            perms.request(.accessibility)
        case .engine where !model.engine.isRunning:
            go(1)   // the brain step waits for the engine itself
        case .brain:
            Task { if await brain.run(model) { go(1) } }
        case .aboutYou:
            Task { await aboutYou.save(model); go(1) }
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

    var body: some View {
        let granted = perms.status(kind) == .granted
        StepLayout(symbol: granted ? "checkmark.circle.fill" : kind.symbol, tint: granted ? .green : .accentColor,
                   title: granted ? "\(kind.title) allowed" : "Allow \(kind.title)",
                   message: granted ? "All set. Press Continue." : kind.why) {
            if !granted {
                VStack(spacing: 10) {
                    if kind == .accessibility {
                        Text("macOS will ask. Choose **Open System Settings**, turn on **Vox**, then come back here.")
                            .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    } else if perms.status(kind) == .denied {
                        Text("Microphone access was turned off earlier. Turn on **Vox** in System Settings → Privacy & Security → Microphone.")
                            .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    }
                    if perms.asked.contains(kind) && kind == .accessibility {
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
                    Button("Try Again") { Task { await installer.install(into: model.engine.location); model.engine.refreshLocation(); model.boot() } }
                default:
                    if !running {
                        if case .failed(let why) = model.engine.state {
                            Text(why).font(.callout).foregroundStyle(.red).multilineTextAlignment(.center)
                            Button("Try Again") { model.boot() }
                        } else {
                            ProgressView().controlSize(.small)
                            // The first start downloads the speech models (Whisper, the voices: about
                            // 0.6 GB) with no progress of its own, so at least show time passing.
                            TimelineView(.periodic(from: .now, by: 1)) { ctx in
                                let secs = max(0, Int(ctx.date.timeIntervalSince(model.engine.since)))
                                Text("Starting the speech engine\u{2026} \(secs / 60):\(String(format: "%02d", secs % 60))")
                                    .font(.callout.monospacedDigit()).foregroundStyle(.secondary)
                            }
                            Text("The first start downloads the speech models (about 0.6 GB). On a slow connection that takes a few minutes. Later starts take seconds.")
                                .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)
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

// MARK: Mic check

/// Proves the microphone works before anything depends on it: a live level bar, and the microphone
/// picker right there for when the bar stays flat (the wrong input, or AirPods asleep).
private struct MicCheckStep: View {
    @Environment(AppModel.self) private var model
    @Binding var heard: Bool
    var preview: MicLevel?

    var body: some View {
        StepLayout(symbol: heard ? "checkmark.circle.fill" : "mic.and.signal.meter", tint: heard ? .green : .accentColor,
                   title: heard ? "Vox can hear you" : "Test your microphone",
                   message: heard ? "The bar moves when you talk. Press Continue."
                                  : "Say a few words, like \u{201C}testing, one, two, three\u{201D}. The bar should jump past the line.") {
            VStack(spacing: 18) {
                MicLevelMeter(preview: preview, heardSpeech: $heard)
                    .frame(maxWidth: 380)
                if model.engine.isRunning || preview != nil {
                    MicPicker().frame(maxWidth: 380)
                    if !heard {
                        Text("Bar not moving? Pick another microphone above, or check it isn't muted. You can also skip this and talk to Vox by typing.")
                            .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    }
                } else {
                    Text("The speech engine isn't running yet. Go back a step to see why, or skip this for now.")
                        .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                }
            }
        }
    }
}

// MARK: Brain

/// The brain step's state, owned by OnboardingView so the footer's Continue can run it.
@MainActor
@Observable
final class BrainSetup {
    enum TestState: Equatable { case idle, testing, passed(Int), failed(String) }

    var choice: BrainPreset = .current { didSet { if choice != oldValue { test = .idle } } }
    private(set) var test: TestState = .idle
    private(set) var keys: [String: Bool] = [:]
    /// Keys typed but not yet saved. Continue (or Return) saves them, so "paste key, press Return"
    /// just works instead of complaining the key is missing.
    var drafts: [String: String] = [:]
    private(set) var keyError: String?
    /// The preset last written to the engine, so a retry doesn't rewrite settings and restart again.
    private var applied: BrainPreset = .current
    var claudeLoggedIn: Bool?
    /// Whether the brains already configured answered the first check. A fresh install's defaults
    /// need accounts a new user doesn't have, so "Keep my current setup" only shows when it works.
    private(set) var currentWorks: Bool?

    var isTesting: Bool { test == .testing }

    /// The choices to show: the current setup only once it has proved it works.
    var presets: [BrainPreset] { BrainPreset.allCases.filter { $0 != .current || currentWorks == true } }

    /// First look: try the current setup. If it doesn't answer, start from the subscription option
    /// instead of showing a red error for a setup the user never chose.
    func checkCurrent(_ model: AppModel) async {
        guard currentWorks == nil, choice == .current else { return }
        currentWorks = await run(model)
        if currentWorks == false {
            choice = .subscription
            test = .idle
        }
    }
    var passed: Bool { if case .passed = test { return true }; return false }

    func refreshKeys(_ model: AppModel) async {
        if let k: [String: Bool] = try? await model.api.get("secrets") { keys = k }
    }

    /// Apply the chosen preset (if any), then prove the brain answers. True when it's working.
    func run(_ model: AppModel) async -> Bool {
        if passed { return true }
        keyError = nil
        for name in choice.keysNeeded where !(keys[name] ?? false) {
            let v = (drafts[name] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard v.count >= 8 else { continue }
            do {
                try await model.api.post("secrets", ["name": .string(name), "value": .string(v)])
                drafts[name] = nil
            } catch {
                keyError = "Couldn't save your \(KeyField.label(for: name)): \(error.localizedDescription)"
                test = .failed(keyError!)
                return false
            }
        }
        await refreshKeys(model)
        if let missing = choice.keysNeeded.first(where: { !(keys[$0] ?? false) }) {
            test = .failed("Paste your \(KeyField.label(for: missing)) above first, or choose another option.")
            return false
        }
        test = .testing
        for _ in 0..<120 where !model.engine.isRunning { try? await Task.sleep(for: .milliseconds(500)) }
        guard model.engine.isRunning else {
            test = .failed("The speech engine isn't running yet. Go back a step to see why, or set this up later.")
            return false
        }
        if choice != applied, let p = await settings(for: choice, model) {
            do {
                for (k, v) in p { try await model.api.setSetting(k, .string(v)) }
            } catch {
                test = .failed("Couldn't switch brains: \(error.localizedDescription)")
                return false
            }
            applied = choice
            model.restartEngine()   // provider changes apply on restart
            try? await Task.sleep(for: .seconds(1))
            for _ in 0..<120 where !model.engine.isRunning { try? await Task.sleep(for: .milliseconds(500)) }
            await model.reloadSettings()
        } else if choice == .openai, choice != applied {
            return false   // settings(for:) has already said why
        }
        struct R: Decodable { var ok: Bool; var reply: String; var ms: Int }
        do {
            let r: R = try await model.api.send("brain/test", method: "POST", body: ["brain": "small"])
            test = r.ok ? .passed(r.ms) : .failed(r.reply)
            return r.ok
        } catch {
            test = .failed(error.localizedDescription)
            return false
        }
    }
}

extension BrainSetup {
    /// The settings a preset writes. OpenAI's model names are read from the account rather than
    /// hard-coded (they change faster than Vox does): its newest "mini" for everyday replies, its
    /// newest full model for hard ones.
    func settings(for preset: BrainPreset, _ model: AppModel) async -> [String: String]? {
        guard preset == .openai else { return preset.settings }
        struct R: Decodable { var models: [String] }
        let ids = ((try? await model.api.get("brain/models?provider=chatgpt", as: R.self))?.models ?? [])
            .filter { $0.range(of: #"^gpt-\d"#, options: .regularExpression) != nil }
        guard let big = ids.first(where: { !$0.contains("mini") && !$0.contains("nano") }) else {
            test = .failed("Your OpenAI key didn't list any GPT models. Check the key, or that the account has credit.")
            return nil
        }
        let small = ids.first(where: { $0.contains("mini") }) ?? big
        return ["small_brain_provider": "chatgpt", "small_brain_model": small,
                "big_brain_provider": "chatgpt", "big_brain_model": big]
    }
}

/// Optional: the apps Vox can use for you (any MCP server, e.g. Composio for Gmail/Calendar/Slack),
/// Spotify, and the Mac's Calendar. The same controls as Settings → Connections.
private struct ConnectionsStep: View {
    var perms: Permissions

    var body: some View {
        StepLayout(symbol: "link", title: "Connect your apps",
                   message: "Optional. Let Vox read your email, calendar and messages, and control Spotify. You can do this later in Settings → Connections.",
                   compact: true) {
            VStack(spacing: 10) {
                HStack {
                    Label("Mac Calendar", systemImage: "calendar")
                    Spacer()
                    if perms.status(.calendar) == .granted {
                        Label("Allowed", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
                    } else {
                        Button("Allow…") { perms.request(.calendar) }
                    }
                }
                .padding(.horizontal, 20)
                ConnectionsPane()
                    .frame(height: 300)
            }
        }
    }
}

private struct BrainStep: View {
    @Environment(AppModel.self) private var model
    var setup: BrainSetup

    var body: some View {
        StepLayout(symbol: "brain", title: "Choose a brain",
                   message: "Vox recognises commands on its own. A language model handles everything else.", compact: true) {
            VStack(spacing: 8) {
                ForEach(setup.presets) { p in
                    PresetRow(preset: p, selected: setup.choice == p, keys: setup.keys, setup: setup) {
                        setup.choice = p
                    }
                }
                ForEach(setup.choice.keysNeeded, id: \.self) { name in
                    KeyField(name: name, isSet: setup.keys[name] ?? false, setup: setup)
                }
                HStack { testStatus; Spacer() }
                    .frame(minHeight: 22)
                    .padding(.top, 4)
                Text("No AI account? Choose Set Up Later: Vox's built-in commands work without one.")
                    .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
        }
        .task {
            await setup.refreshKeys(model)
            setup.claudeLoggedIn = await ClaudeCLI.loggedIn(venv: model.engine.location.venvDir)
            // Keeping the current setup needs nothing from the user, so check it straight away.
            await setup.checkCurrent(model)
        }
    }

    @ViewBuilder private var testStatus: some View {
        switch setup.test {
        case .idle:
            Text(setup.choice == .current ? "Press Continue to check it works."
                 : setup.choice == .subscription && setup.claudeLoggedIn != true ? "Sign in to Claude first, then press Continue."
                 : "Press Continue to switch and test it.")
                .font(.callout).foregroundStyle(.secondary)
        case .testing:
            HStack(spacing: 6) { ProgressView().controlSize(.small); Text("Checking the brain answers…").foregroundStyle(.secondary) }
        case .passed(let ms):
            Label("Working. Replied in \(String(format: "%.1f", Double(ms) / 1000)) s", systemImage: "checkmark.circle.fill")
                .foregroundStyle(.green)
        case .failed(let why):
            Label(why, systemImage: "xmark.octagon.fill").foregroundStyle(.red).lineLimit(3).font(.callout)
        }
    }
}

enum BrainPreset: String, CaseIterable, Identifiable {
    case current, subscription, anthropic, openai, fast
    var id: String { rawValue }

    var title: String {
        switch self {
        case .current: "Keep my current setup"
        case .fast: "Fast and cheap"
        case .anthropic: "Claude via API"
        case .openai: "ChatGPT models via API"
        case .subscription: "Claude subscription"
        }
    }

    var detail: String {
        switch self {
        case .current: "Use the brains already configured."
        case .fast: "DeepSeek for everyday replies (about 1 s, fractions of a cent), Claude for hard ones."
        case .anthropic: "Claude Haiku for everyday replies, Sonnet for hard ones. Pay per use."
        case .openai: "GPT models on an OpenAI API key (not a ChatGPT plan). Pay per use."
        case .subscription: "Uses your Claude Pro or Max plan. No per-use cost, but slower (2–5 s)."
        }
    }

    var keysNeeded: [String] {
        switch self {
        case .fast: ["DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY"]
        case .anthropic: ["ANTHROPIC_API_KEY"]
        case .openai: ["OPENAI_API_KEY"]
        default: []
        }
    }

    var settings: [String: String]? {
        switch self {
        case .current, .openai: nil   // openai: read from the account, see BrainSetup.settings(for:)
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
    var setup: BrainSetup
    var select: () -> Void
    @Environment(AppModel.self) private var model

    var body: some View {
        Button(action: select) {
            HStack(spacing: 12) {
                Image(systemName: selected ? "largecircle.fill.circle" : "circle")
                    .foregroundStyle(selected ? Color.accentColor : Color.secondary).font(.title3)
                VStack(alignment: .leading, spacing: 2) {
                    Text(preset.title).font(.body.weight(.medium))
                    Text(preset.detail).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    if preset == .subscription, setup.claudeLoggedIn == true {
                        Label("Signed in to Claude", systemImage: "checkmark.circle.fill").font(.caption).foregroundStyle(.green)
                    } else if preset == .subscription, selected {
                        HStack(spacing: 8) {
                            Button("Sign in to Claude\u{2026}") { ClaudeCLI.openSignIn(venv: model.engine.location.venvDir) }
                                .help("Opens a Terminal window, then your browser. Sign in there, come back and press Check Again.")
                            Button("Check Again") {
                                Task { setup.claudeLoggedIn = await ClaudeCLI.loggedIn(venv: model.engine.location.venvDir) }
                            }
                        }
                        .controlSize(.small).padding(.top, 2)
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
    var name: String
    var isSet: Bool
    var setup: BrainSetup

    private var label: String { Self.label(for: name) }

    static func label(for name: String) -> String {
        switch name {
        case "DEEPSEEK_API_KEY": "DeepSeek API key"
        case "ANTHROPIC_API_KEY": "Anthropic API key"
        case "OPENAI_API_KEY": "OpenAI API key"
        default: name
        }
    }

    /// Where to create one, for someone who has never made an API key.
    static func page(for name: String) -> URL? {
        switch name {
        case "DEEPSEEK_API_KEY": URL(string: "https://platform.deepseek.com/api_keys")
        case "ANTHROPIC_API_KEY": URL(string: "https://console.anthropic.com/settings/keys")
        case "OPENAI_API_KEY": URL(string: "https://platform.openai.com/api-keys")
        default: nil
        }
    }

    var body: some View {
        HStack {
            if isSet {
                Label("\(label) saved", systemImage: "key.fill").foregroundStyle(.green).font(.callout)
                Spacer()
            } else {
                // Saved when you press Continue (or Return): one action, not two.
                SecureField("Paste your \(label)", text: Binding(
                    get: { setup.drafts[name] ?? "" }, set: { setup.drafts[name] = $0 }))
                    .textFieldStyle(.roundedBorder)
                    .help("Saved to Vox's private settings file on this Mac, readable only by you.")
                if let url = Self.page(for: name) {
                    Link("Get a key", destination: url).font(.callout)
                }
            }
        }
    }
}

/// Is Claude signed in for the subscription brain? Uses an installed Claude Code if there is one,
/// else the copy the engine's Agent SDK ships with, so nobody has to install Claude Code first: both
/// share the same sign-in. Reads only the `loggedIn` flag: the full output includes the account
/// email, which isn't shown or kept.
enum ClaudeCLI {
    static func binary(venv: URL) -> URL? {
        let onPath = EngineLocation.childPATH.split(separator: ":")
            .map { URL(fileURLWithPath: String($0)).appending(path: "claude") }
        let bundled = venv.appending(path: "lib/python3.12/site-packages/claude_agent_sdk/_bundled/claude")
        return (onPath + [bundled]).first { FileManager.default.isExecutableFile(atPath: $0.path) }
    }

    /// Sign-in is interactive (a browser, sometimes a code to paste), so it runs in a Terminal
    /// window the user can see, opened via a .command file: no Automation permission needed.
    static func openSignIn(venv: URL) {
        guard let bin = binary(venv: venv) else { return }
        let file = FileManager.default.temporaryDirectory.appending(path: "vox-claude-sign-in.command")
        let script = """
        #!/bin/bash
        echo "Signing in to Claude for Vox. Your browser will open."
        echo
        '\(bin.path.replacingOccurrences(of: "'", with: "'\\''"))' auth login --claudeai
        echo
        echo "All done. Go back to Vox and press Check Again. You can close this window."
        """
        try? script.write(to: file, atomically: true, encoding: .utf8)
        try? FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: file.path)
        NSWorkspace.shared.open(file)
    }

    static func loggedIn(venv: URL) async -> Bool? {
        await Task.detached { () -> Bool? in
            guard let bin = binary(venv: venv) else { return false }
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

// MARK: Voice

private struct VoiceStep: View {
    @Environment(AppModel.self) private var model
    @State private var previewing: String?
    @State private var kokoro: KokoroStatus?

    /// The voices are a one-time ~350 MB download. Until it's done a preview has nothing to play.
    private struct KokoroStatus: Decodable {
        var state: String
        var downloadedMB: Int
        var error: String
    }

    /// Unknown (engine not answering yet) counts as ready, so the buttons behave as they always did.
    private var voicesReady: Bool { kokoro == nil || kokoro?.state == "ready" }

    private var voices: [SettingOption] { model.setting("kokoro_voice")?.options ?? [] }
    private var current: String { model.value("kokoro_voice").string }

    var body: some View {
        StepLayout(symbol: "speaker.wave.2.fill", title: "Pick a voice",
                   message: "This is how Vox answers you. Press play to hear each one.", compact: true) {
            if voices.isEmpty {
                Text("The voices appear once the speech engine is running. Press Continue to carry on, and pick a voice later in Settings \u{2192} Voice.")
                    .foregroundStyle(.secondary).multilineTextAlignment(.center)
            } else {
                downloadStatus
                ScrollView {
                    VStack(spacing: 6) {
                        ForEach(voices, id: \.value) { v in row(v) }
                    }
                    .padding(2)
                }
                .frame(maxHeight: 280)
            }
        }
        .task(id: voices.isEmpty) { await prepareVoices() }
    }

    @ViewBuilder private var downloadStatus: some View {
        if let k = kokoro {
            switch k.state {
            case "downloading":
                Label("Downloading the voices (about 350 MB)\u{2026} \(k.downloadedMB) MB so far", systemImage: "arrow.down.circle")
                    .font(.callout).foregroundStyle(.secondary)
            case "idle", "loading":
                Label("Getting the voices ready\u{2026}", systemImage: "hourglass")
                    .font(.callout).foregroundStyle(.secondary)
            case "error":
                VStack(spacing: 6) {
                    Label("Couldn't download the voices: \(k.error). Until they're here, Vox uses your Mac's built-in voice.",
                          systemImage: "exclamationmark.triangle")
                        .font(.callout).foregroundStyle(.orange).multilineTextAlignment(.center)
                    Button("Try again") { Task { await prepareVoices() } }
                }
            default:
                EmptyView()
            }
        }
    }

    /// Start the voice download as soon as this step opens, then follow it until it's done.
    private func prepareVoices() async {
        kokoro = try? await model.api.send("voices/kokoro/prepare", method: "POST", body: [String: JSONValue]())
        while !Task.isCancelled, let k = kokoro, k.state != "ready", k.state != "error" {
            try? await Task.sleep(for: .milliseconds(500))
            if let next: KokoroStatus = try? await model.api.get("voices/kokoro") { kokoro = next }
        }
    }

    private func row(_ v: SettingOption) -> some View {
        let selected = v.value == current
        return HStack(spacing: 12) {
            Image(systemName: selected ? "largecircle.fill.circle" : "circle")
                .foregroundStyle(selected ? Color.accentColor : Color.secondary)
            VStack(alignment: .leading, spacing: 1) {
                Text(Self.name(v)).font(.body.weight(selected ? .semibold : .regular))
                Text(Self.detail(v)).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Button {
                previewing = v.value
                Task {
                    try? await model.api.post("voices/preview", ["engine": .string("kokoro"), "voice": .string(v.value)])
                    try? await Task.sleep(for: .seconds(4))
                    if previewing == v.value { previewing = nil }
                }
            } label: {
                Image(systemName: previewing == v.value ? "speaker.wave.2.fill" : "play.circle")
                    .font(.title3)
            }
            .buttonStyle(.plain).foregroundStyle(voicesReady ? Color.accentColor : Color.secondary)
            .disabled(!voicesReady)
            .accessibilityLabel("Play \(Self.name(v))")
        }
        .padding(.horizontal, 12).padding(.vertical, 8)
        .contentShape(Rectangle())
        .background(selected ? Color.accentColor.opacity(0.08) : .clear, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous)
            .strokeBorder(selected ? Color.accentColor.opacity(0.5) : Color.secondary.opacity(0.15)))
        .onTapGesture {
            model.set("kokoro_voice", .string(v.value))
            model.set("tts_engine", .string("kokoro"))
        }
    }

    /// "af_bella — US ♀" → "Bella"
    static func name(_ v: SettingOption) -> String {
        let raw = v.value.split(separator: "_").last.map(String.init) ?? v.value
        return raw.prefix(1).uppercased() + raw.dropFirst()
    }

    static func detail(_ v: SettingOption) -> String {
        let accent = v.value.hasPrefix("b") ? "British" : "American"
        let who = v.value.dropFirst().hasPrefix("f") ? "female" : "male"
        var flavour = ""
        if let open = v.label.range(of: "(") {
            flavour = String(v.label[open.lowerBound...]).trimmingCharacters(in: CharacterSet(charactersIn: "()"))
            if flavour == "default" || flavour.hasPrefix("warm, default") { flavour = "warm" }
        }
        return [accent + " " + who, flavour].filter { !$0.isEmpty }.joined(separator: " · ")
    }
}

// MARK: About you

@MainActor
@Observable
final class AboutYouSetup {
    var observation = ""
    var questions: [String] = []
    var answers: [String: String] = [:]
    var loading = false
    var loaded = false

    func load(_ model: AppModel) async {
        guard !loaded, !loading else { return }
        loading = true
        struct R: Decodable { var observation: String; var questions: [String] }
        if let r: R = try? await model.api.get("onboarding/questions") {
            observation = r.observation
            questions = r.questions
        } else {
            questions = ["What should I call you?", "What do you mostly use your Mac for?"]
        }
        loading = false
        loaded = true
    }

    func save(_ model: AppModel) async {
        struct Body: Encodable { var answers: [[String: String]] }
        let body = Body(answers: questions.compactMap { q in
            let a = (answers[q] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            return a.isEmpty ? nil : ["question": q, "answer": a]
        })
        guard !body.answers.isEmpty else { return }
        let _: Empty? = try? await model.api.send("onboarding/answers", method: "POST", body: body)
    }
}

private struct AboutYouStep: View {
    @Environment(AppModel.self) private var model
    var setup: AboutYouSetup
    @State private var recorder = SampleRecorder()
    @State private var recordingFor: String?
    @State private var transcribing: String?

    var body: some View {
        StepLayout(symbol: "person.text.rectangle", title: "A little about you",
                   message: setup.observation.isEmpty ? "So Vox can be more helpful from day one. All optional." : setup.observation,
                   compact: true) {
            VStack(alignment: .leading, spacing: 10) {
                if setup.loading {
                    HStack(spacing: 8) { ProgressView().controlSize(.small); Text("Looking at your apps…").foregroundStyle(.secondary) }
                        .frame(maxWidth: .infinity)
                } else {
                    ForEach(setup.questions, id: \.self) { q in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(q).font(.callout.weight(.medium))
                            HStack(spacing: 8) {
                                TextField(transcribing == q ? "Listening back…" : "Type, or press the mic and say it",
                                          text: Binding(get: { setup.answers[q] ?? "" }, set: { setup.answers[q] = $0 }))
                                    .textFieldStyle(.roundedBorder)
                                Button { Task { await toggleMic(q) } } label: {
                                    Image(systemName: recordingFor == q ? "stop.circle.fill" : "mic.circle")
                                        .font(.title2)
                                        .foregroundStyle(recordingFor == q ? Color.red : Color.accentColor)
                                }
                                .buttonStyle(.plain)
                                .disabled(recordingFor != nil && recordingFor != q)
                                .help(recordingFor == q ? "Stop and use what you said" : "Answer by voice")
                                .accessibilityLabel(recordingFor == q ? "Stop recording" : "Answer by voice")
                            }
                        }
                    }
                    Text("Vox looked only at the names of your apps. Answers are saved to Memory, where you can see and edit them.")
                        .font(.caption).foregroundStyle(.secondary).padding(.top, 4)
                }
            }
        }
        .task { await setup.load(model) }
        .onDisappear { if recorder.isRecording { _ = recorder.stop(); Task { try? await model.api.setPaused(false) } } }
    }

    /// Record an answer, then let the engine transcribe it. Vox ignores the mic meanwhile, so an
    /// answer like "call me Sam" isn't also taken as a command.
    private func toggleMic(_ q: String) async {
        if recordingFor == q {
            let wav = recorder.stop()
            recordingFor = nil
            try? await model.api.setPaused(false)
            guard let wav else { return }
            transcribing = q
            defer { transcribing = nil }
            struct R: Decodable { var text: String }
            if let r: R = try? await model.api.send("transcribe", method: "POST", body: ["audio": wav.base64EncodedString()]),
               !r.text.isEmpty {
                let existing = (setup.answers[q] ?? "").trimmingCharacters(in: .whitespaces)
                setup.answers[q] = existing.isEmpty ? r.text : existing + " " + r.text
            }
        } else {
            try? await model.api.setPaused(true)
            do { try recorder.start(); recordingFor = q }
            catch { try? await model.api.setPaused(false) }
        }
    }
}

// MARK: Try it + done

private struct TryItStep: View {
    @Environment(AppModel.self) private var model
    var perms: Permissions
    var meterPreview: MicLevel?
    @State private var since = Date()

    /// The first thing said (or typed) since this step appeared, and Vox's answer to it.
    private var heard: Turn? { model.turns.first { $0.isUser && ($0.date ?? .distantPast) > since } }
    private var reply: Turn? {
        guard let h = heard else { return nil }
        return model.turns.first { !$0.isUser && ($0.date ?? .distantPast) >= (h.date ?? since) }
    }
    private var canHear: Bool { perms.status(.microphone) == .granted && model.engine.isRunning }

    var body: some View {
        StepLayout(symbol: heard == nil ? (canHear ? "mic.and.signal.meter" : "keyboard") : "checkmark.circle.fill",
                   tint: heard == nil ? .accentColor : .green,
                   title: heard == nil ? "Say hello" : "Vox heard you",
                   message: heard.map { "\u{201C}\($0.text)\u{201D}" }
                       ?? (canHear ? "Say \u{201C}Hey Vox, what time is it?\u{201D}" : "Vox can't hear you yet, but you can type to it.")) {
            VStack(spacing: 10) {
                if heard == nil {
                    if canHear || meterPreview != nil {
                        MicLevelMeter(preview: meterPreview).frame(maxWidth: 380)
                        Text("Can't talk right now? Type instead:").font(.callout).foregroundStyle(.secondary).padding(.top, 8)
                    }
                    if model.engine.isRunning { AskField(compact: true) }
                } else if let reply {
                    Text(reply.text).font(.callout).padding(10).frame(maxWidth: .infinity)
                        .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 10))
                }
            }
        }
        .onAppear { since = Date() }
    }
}

private struct DoneStep: View {
    @Environment(AppModel.self) private var model
    var perms: Permissions

    private var message: String {
        if !model.engine.isRunning { return "Vox will start when you open it from the menu bar." }
        if perms.status(.microphone) != .granted { return "Vox can't hear you until you allow the microphone in Settings → Permissions." }
        return "Vox is listening. Find it in your menu bar any time."
    }

    var body: some View {
        StepLayout(symbol: "checkmark.seal.fill", tint: .green, title: "You're all set", message: message) {
            VStack(alignment: .leading, spacing: 10) {
                Bullet(symbol: "command", text: "\u{201C}Take control\u{201D} to give commands. \u{201C}Stand down\u{201D} to stop.")
                Bullet(symbol: "bubble.left", text: "\u{201C}Hey Vox\u{201D} to ask a question or chat.")
                Bullet(symbol: "keyboard", text: "\u{201C}Start typing\u{201D} to dictate into any text field.")
                Bullet(symbol: "option", text: "Or hold the right \u{2325} Option key, talk, and let go. No wake word needed.")
            }
        }
    }
}

extension AboutYouSetup {
    /// Filled-in questions for `--snapshot`, so the step renders without a live engine.
    static var sample: AboutYouSetup {
        let s = AboutYouSetup()
        s.observation = "You've got Logic Pro, Figma and Xcode: a maker, then."
        s.questions = ["What should I call you?",
                       "I saw you have Logic Pro: do you make music for work or for fun?",
                       "I saw you have Figma: what kind of things do you design?"]
        s.answers = [s.questions[0]: "Sam"]
        s.loaded = true
        return s
    }
}
