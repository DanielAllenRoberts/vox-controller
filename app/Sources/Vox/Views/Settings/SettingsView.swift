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
    var body: some View {
        HStack {
            Label("Start Vox to change these settings.", systemImage: "power").foregroundStyle(.secondary)
            Spacer()
            Button("Start Vox") { model.engine.start() }
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
        }
    }

    @ViewBuilder
    private func control(_ s: Setting) -> some View {
        switch s.type {
        case "toggle":
            Toggle(isOn: model.binding(bool: s.key)) { label }
        case "select":
            Picker(selection: model.binding(string: s.key)) {
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

    /// Model menus only offer models the chosen provider can run (plus the current value, so a
    /// custom model set in config still shows).
    private func options(for s: Setting) -> [SettingOption] {
        var opts = s.options ?? []
        let brain = s.key.hasPrefix("small_brain") ? "small_brain" : s.key.hasPrefix("big_brain") ? "big_brain" : nil
        if let brain, s.key.hasSuffix("_model") {
            let provider = model.value("\(brain)_provider").string
            opts = opts.filter { o in
                switch provider {
                case "claude_sdk", "anthropic", "claude_cli": o.value.hasPrefix("claude")
                case "openai": !o.value.hasPrefix("claude") && !o.value.contains("/")
                case "local_ai": o.value.contains("/")
                default: true
                }
            }
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
        .onAppear { perms.refresh() }
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
                    Button("Restart Engine") { model.engine.restart() }
                    if model.engine.isRunning {
                        Button("Stop Engine") { Task { await model.engine.stop() } }
                    } else {
                        Button("Start Engine") { model.engine.start() }
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
                    Button("Run Setup Again…") { NotificationCenter.default.post(name: .voxShowOnboarding, object: nil) }
                    Spacer()
                }
            }
        }
        .formStyle(.grouped)
    }
}
