import ServiceManagement
import SwiftUI

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @AppStorage("settingsTab") private var tab: SettingsTab = .general

    var body: some View {
        TabView(selection: $tab) {
            ForEach(SettingsTab.allCases) { t in
                content(for: t)
                    .tabItem { Label(t.title, systemImage: t.symbol) }
                    .tag(t)
            }
        }
        .frame(width: 620, height: 600)
        .task { await model.reloadSettings() }
    }

    @ViewBuilder
    private func content(for t: SettingsTab) -> some View {
        switch t {
        case .permissions: PermissionsPane()
        case .advanced: AdvancedPane()
        case .general: CatalogPane(tab: t) { AppBehaviourSection() }
        case .listening: CatalogPane(tab: t) { HoldToTalkSection() }
        default: CatalogPane(tab: t) { EmptyView() }
        }
    }
}

/// A tab rendered from the catalog, with optional app-side sections above it.
private struct CatalogPane<Header: View>: View {
    @Environment(AppModel.self) private var model
    var tab: SettingsTab
    @ViewBuilder var header: Header

    var body: some View {
        Form {
            if model.restartNeeded {
                Section {
                    HStack {
                        Label("Some changes take effect after Vox restarts.", systemImage: "arrow.clockwise.circle")
                        Spacer()
                        Button("Restart Now") { model.restartEngine() }
                    }
                }
            }
            header
            if model.engine.isRunning {
                ForEach(SettingsCatalog.tabs[tab] ?? [], id: \.title) { section in
                    let rows = section.items.filter { model.setting($0.key) != nil }
                    if !rows.isEmpty {
                        Section {
                            ForEach(rows, id: \.key) { spec in SettingRow(spec: spec) }
                        } header: {
                            Text(section.title)
                        } footer: {
                            if let f = section.footer { Text(f).foregroundStyle(.secondary) }
                        }
                    }
                }
            } else {
                Section { EngineNotice() }
            }
            if let err = model.settingsError {
                Section { Label(err, systemImage: "exclamationmark.triangle").foregroundStyle(.red) }
            }
        }
        .formStyle(.grouped)
    }
}

private struct EngineNotice: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow
    var body: some View {
        HStack {
            if model.engine.isStarting {
                Label("Vox is starting…", systemImage: "hourglass").foregroundStyle(.secondary)
                Spacer()
                ProgressView().controlSize(.small)
            } else if model.engine.state == .notInstalled {
                Label("Vox isn't set up yet.", systemImage: "wrench.and.screwdriver").foregroundStyle(.secondary)
                Spacer()
                Button("Open Setup…") { openWindow(id: "onboarding"); NSApp.activate() }
            } else {
                Label("Start Vox to change these settings.", systemImage: "power").foregroundStyle(.secondary)
                Spacer()
                Button("Start Vox") { model.boot() }
            }
        }
    }
}

/// One engine setting, drawn by type: switch, menu, or field.
struct SettingRow: View {
    @Environment(AppModel.self) private var model
    var spec: SettingSpec

    var body: some View {
        if let s = model.setting(spec.key) {
            control(s).help(s.help)
                .onChange(of: model.value(spec.key)) { old, new in
                    if old != .null && old != new && SettingsCatalog.needsRestart(s) { model.noteRestartNeeded() }
                }
        }
    }

    @ViewBuilder
    private func control(_ s: Setting) -> some View {
        switch s.type {
        case "toggle":
            Toggle(isOn: model.binding(bool: s.key)) { label }
        case "select":
            Picker(selection: selectBinding(s)) {
                ForEach(options(for: s), id: \.value) { o in Text(o.label).tag(o.value) }
            } label: { label }
        default:
            LabeledContent { NumberOrTextField(key: s.key) } label: { label }
        }
    }

    private var label: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(spec.label)
            if let c = spec.caption { Text(c).font(.caption).foregroundStyle(.secondary) }
            if let s = model.setting(spec.key), SettingsCatalog.needsRestart(s) {
                Text("Takes effect after Vox restarts.").font(.caption).foregroundStyle(.tertiary)
            }
        }
    }

    /// Choosing a provider also switches the model if the current one can't run there (Anthropic
    /// can't run DeepSeek), instead of leaving a mismatched pair that only fails at the next reply.
    private func selectBinding(_ s: Setting) -> Binding<String> {
        guard s.key.hasSuffix("_brain_provider") else { return model.binding(string: s.key) }
        let brain = String(s.key.dropLast("_provider".count))
        return Binding(get: { model.value(s.key).string }, set: { provider in
            model.set(s.key, .string(provider))
            let modelKey = "\(brain)_model"
            let current = model.value(modelKey).string
            if !Self.runs(current, on: provider),
               let pick = model.setting(modelKey)?.options?.first(where: { Self.runs($0.value, on: provider) }) {
                model.set(modelKey, .string(pick.value))
            }
        })
    }

    static func runs(_ modelID: String, on provider: String) -> Bool {
        switch provider {
        case "claude_sdk", "anthropic", "claude_cli": modelID.hasPrefix("claude")
        case "openai": !modelID.hasPrefix("claude") && !modelID.contains("/")
        case "local_ai": modelID.contains("/")
        default: true
        }
    }

    /// Model menus only offer models the chosen provider can run (plus the current value, so a
    /// custom model set in config still shows).
    private func options(for s: Setting) -> [SettingOption] {
        var opts = s.options ?? []
        let brain = s.key.hasPrefix("small_brain") ? "small_brain" : s.key.hasPrefix("big_brain") ? "big_brain" : nil
        if let brain, s.key.hasSuffix("_model") {
            let provider = model.value("\(brain)_provider").string
            opts = opts.filter { Self.runs($0.value, on: provider) }
            opts = opts.map { SettingOption(value: $0.value, label: BrainNames.model($0.value)) }
        }
        if s.key.hasSuffix("_provider") {
            opts = opts.map { SettingOption(value: $0.value, label: BrainNames.providerOption($0.value)) }
        }
        let current = s.value.string
        if !current.isEmpty && !opts.contains(where: { $0.value == current }) {
            opts.insert(SettingOption(value: current, label: BrainNames.model(current)), at: 0)
        }
        return opts
    }
}

/// Text/number settings commit on Return or when focus leaves, not on every keystroke.
private struct NumberOrTextField: View {
    @Environment(AppModel.self) private var model
    var key: String
    @State private var draft = ""
    @FocusState private var focused: Bool

    var body: some View {
        TextField("", text: $draft)
            .multilineTextAlignment(.trailing)
            .frame(width: 120)
            .focused($focused)
            .onSubmit(commit)
            .onChange(of: focused) { _, f in if !f { commit() } }
            .onAppear { draft = model.value(key).string }
            // Follow the real value (changed by voice, or restored after a refused edit) unless the
            // user is typing in this field. A field seeded once could later write a stale value back.
            .onChange(of: model.value(key)) { _, v in if !focused { draft = v.string } }
    }

    private func commit() {
        guard draft != model.value(key).string else { return }
        if let s = model.setting(key), s.type == "number", let n = Double(draft) {
            model.set(key, .number(n))
        } else {
            model.set(key, .string(draft))
        }
    }
}

// MARK: General: app behaviour (Vox.app's own settings, not the engine's)

private struct AppBehaviourSection: View {
    @AppStorage("quitEngineWithApp") private var quitEngine = true
    @State private var launchAtLogin = SMAppService.mainApp.status == .enabled
    @State private var loginError: String?

    var body: some View {
        Section("Vox app") {
            Toggle(isOn: $launchAtLogin) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Open Vox at login")
                    if let loginError { Text(loginError).font(.caption).foregroundStyle(.red) }
                }
            }
            .onChange(of: launchAtLogin) { _, on in
                do {
                    if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
                    loginError = nil
                } catch {
                    loginError = error.localizedDescription
                    launchAtLogin = SMAppService.mainApp.status == .enabled
                }
            }
            Toggle(isOn: $quitEngine) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Stop listening when Vox quits")
                    Text("Closing the window keeps Vox in the menu bar either way.").font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }
}

private struct HoldToTalkSection: View {
    @State private var on = HoldToTalk.enabled

    var body: some View {
        Section {
            Toggle(isOn: $on) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Hold Right Option to talk")
                    Text("Hold the key, speak, let go. Works in any mode without a wake word, and letting go ends the turn instantly.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            .onChange(of: on) { _, v in HoldToTalk.enabled = v }
        } header: {
            Text("Hold to talk")
        }
    }
}

// MARK: Permissions

private struct PermissionsPane: View {
    @State private var perms = Permissions()
    @Environment(\.scenePhase) private var phase

    var body: some View {
        Form {
            Section {
                ForEach(Permissions.Kind.allCases) { k in PermissionRow(kind: k, perms: perms) }
            } footer: {
                Text("Vox asks macOS for these on its own behalf, and the speech engine it runs inherits them. After changing one in System Settings, restart Vox.")
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .task {   // System Settings sends no change notification; re-check while this tab is open
            while !Task.isCancelled {
                perms.refresh()
                try? await Task.sleep(for: .seconds(2))
            }
        }
        .onChange(of: phase) { _, _ in perms.refresh() }
    }
}

struct PermissionRow: View {
    var kind: Permissions.Kind
    var perms: Permissions

    var body: some View {
        let st = perms.status(kind)
        HStack(spacing: 12) {
            Image(systemName: kind.symbol)
                .font(.title3).frame(width: 28)
                .foregroundStyle(st == .granted ? Color.green : Color.secondary)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(kind.title)
                    if !kind.required { Text("Optional").font(.caption2).foregroundStyle(.secondary)
                        .padding(.horizontal, 5).padding(.vertical, 1).background(.quaternary, in: Capsule()) }
                }
                Text(kind.why).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if st == .granted {
                Label("Allowed", systemImage: "checkmark.circle.fill").labelStyle(.titleAndIcon)
                    .foregroundStyle(.green).font(.callout)
            } else {
                Button(st == .denied ? "Open Settings…" : "Allow…") { perms.request(kind) }
            }
        }
        .padding(.vertical, 2)
    }
}

// MARK: Advanced

private struct AdvancedPane: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow
    @Environment(\.dismissWindow) private var dismissWindow

    var body: some View {
        Form {
            Section("Engine") {
                LabeledContent("Status") {
                    Text(VoxPresence.from(engine: model.engine.state, status: model.engine.status).title)
                }
                LabeledContent("Runs from") {
                    Text(model.engine.location.kind == .checkout ? "Source checkout" : "Installed engine")
                        .help(model.engine.location.engineDir.path)
                }
                if let v = model.engine.status?.version { LabeledContent("Version", value: v) }
                HStack {
                    Button("Restart Engine") { model.restartEngine() }
                    if model.engine.isRunning {
                        Button("Stop Engine") { Task { await model.engine.stop() } }
                    } else if model.engine.isStarting {
                        ProgressView().controlSize(.small)
                        Text("Starting…").foregroundStyle(.secondary)
                    } else {
                        Button("Start Engine") { model.boot() }
                    }
                    Spacer()
                }
            }
            Section("Files") {
                HStack {
                    Button("Show Data Folder") { NSWorkspace.shared.open(model.engine.location.resolvedDataDir) }
                    Button("Open Log") { NSWorkspace.shared.open(model.engine.location.logFile) }
                    Button("Open Console Output") { NSWorkspace.shared.open(EngineSupervisor.consoleLogURL) }
                    Spacer()
                }
            }
            if model.engine.isRunning {
                ForEach(SettingsCatalog.tabs[.advanced] ?? [], id: \.title) { section in
                    Section(section.title) {
                        ForEach(section.items.filter { model.setting($0.key) != nil }, id: \.key) { SettingRow(spec: $0) }
                    }
                }
                let other = model.settings.filter { !SettingsCatalog.knownKeys.contains($0.key) }
                if !other.isEmpty {
                    Section {
                        ForEach(other) { s in SettingRow(spec: SettingSpec(key: s.key, label: s.label, caption: nil)) }
                    } header: { Text("Other") } footer: { Text("Settings this version of the app doesn't have a place for yet.") }
                }
            }
            Section("Setup") {
                HStack {
                    Button("Run Setup Again…") { openWindow(id: "onboarding"); dismissWindow(id: "main"); NSApp.activate() }
                    Spacer()
                }
            }
        }
        .formStyle(.grouped)
    }
}
