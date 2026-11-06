import AppKit
import SwiftUI

/// Standing instructions the brain follows in every conversation.
struct RulesView: View {
    @Environment(AppModel.self) private var model
    @State private var rules: [Rule] = []
    @State private var loaded = false
    @State private var error: String?
    @State private var loadError: String?
    @State private var draft = ""
    @State private var draftApp: String?
    @State private var pendingDelete: Rule?
    @FocusState private var addFocused: Bool

    private var trimmedDraft: String { draft.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        RequiresEngine {
            Group {
                if loaded {
                    form
                } else if let loadError {
                    LoadErrorView(title: "Couldn't load your rules", message: loadError) { Task { await load() } }
                } else {
                    PageLoading()
                }
            }
            .pageErrors($error, loadError: $loadError, loaded: loaded)
            .refreshesPage(load)
            .toolbar {
                ToolbarItem {
                    Button("New Rule", systemImage: "plus") { addFocused = true }
                        .help("Add a rule")
                }
            }
            .confirmationDialog("Delete this rule?", isPresented: deleteBinding, titleVisibility: .visible,
                                presenting: pendingDelete) { rule in
                Button("Delete Rule", role: .destructive) { delete(rule) }
            } message: { rule in
                Text("\u{201C}\(rule.text)\u{201D}\nVox will stop following it.")
            }
        }
    }

    private var form: some View {
        Form {
            Section {
                HStack(spacing: 12) {
                    TextField("New rule", text: $draft,
                              prompt: Text("Add a rule, like \u{201C}Keep answers to one or two sentences\u{201D}"),
                              axis: .vertical)
                        .labelsHidden()
                        .textFieldStyle(.plain)
                        .focused($addFocused)
                        .onSubmit(add)
                    AppScopePicker(app: $draftApp)
                    Button("Add", action: add).disabled(trimmedDraft.isEmpty)
                }
            } footer: {
                Text("Rules are standing instructions Vox follows. Give a rule an app and it only applies while that app is in front, like \u{201C}in Zen, refresh means ⌘R\u{201D}. You can also say \u{201C}from now on in Zen, when I say refresh, press command R\u{201D}.")
                    .foregroundStyle(.secondary)
            }

            Section {
                if rules.isEmpty {
                    ContentUnavailableView("No rules yet", systemImage: "list.bullet.rectangle",
                                           description: Text("Add one above. For example, how you like to be addressed, or what Vox should never do."))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, Metrics.gap)
                } else {
                    ForEach(rules) { rule in
                        RuleRow(rule: rule,
                                onApp: { setApp(rule, $0) },
                                onToggle: { setEnabled(rule, $0) },
                                onCommit: { rename(rule, $0) },
                                onDelete: { pendingDelete = rule })
                    }
                }
            } header: {
                if !rules.isEmpty {
                    Text(rules.count == 1 ? "1 rule" : "\(rules.count) rules").pageSectionHeader()
                }
            }
        }
        .formStyle(.grouped)
    }

    private var deleteBinding: Binding<Bool> {
        Binding(get: { pendingDelete != nil }, set: { if !$0 { pendingDelete = nil } })
    }

    // MARK: Data

    private func load() async {
        do { rules = try await model.api.get("rules"); loaded = true; loadError = nil }
        catch { loadError = ErrorWords.reason(error) }
    }

    private func setApp(_ rule: Rule, _ app: String?) {
        if let i = rules.firstIndex(where: { $0.id == rule.id }) { rules[i].app = app }
        Task {
            do { try await model.api.patch("rules/\(rule.id)", ["app": app.map { .string($0) } ?? .null]) }
            catch { self.error = ErrorWords.message("Couldn't change that rule.", error); await load() }
        }
    }

    private func add() {
        let text = trimmedDraft
        guard !text.isEmpty else { return }
        draft = ""
        let app = draftApp
        Task {
            do { try await model.api.post("rules", ["text": .string(text), "app": app.map { .string($0) } ?? .null]); await load() }
            catch { draft = text; self.error = ErrorWords.message("Couldn't add that rule.", error) }
        }
    }

    private func setEnabled(_ rule: Rule, _ on: Bool) {
        mutate(rule.id, "Couldn't change that rule.") { $0.enabled = on } send: {
            try await model.api.patch("rules/\(rule.id)", ["enabled": .bool(on)])
        }
    }

    private func rename(_ rule: Rule, _ text: String) {
        mutate(rule.id, "Couldn't save that rule.") { $0.text = text } send: {
            try await model.api.patch("rules/\(rule.id)", ["text": .string(text)])
        }
    }

    private func delete(_ rule: Rule) {
        withAnimation(.smooth) { rules.removeAll { $0.id == rule.id } }
        Task {
            do { try await model.api.delete("rules/\(rule.id)") }
            catch { self.error = ErrorWords.message("Couldn't delete that rule.", error); await load() }
        }
    }

    /// Optimistic: change the row now, persist, and re-read on failure so the list never lies.
    private func mutate(_ id: String, _ failure: String, _ change: (inout Rule) -> Void,
                        send: @escaping () async throws -> Void) {
        guard let i = rules.firstIndex(where: { $0.id == id }) else { return }
        change(&rules[i])
        Task {
            do { try await send() }
            catch { self.error = ErrorWords.message(failure, error); await load() }
        }
    }
}

private struct RuleRow: View {
    var rule: Rule
    var onApp: (String?) -> Void
    var onToggle: (Bool) -> Void
    var onCommit: (String) -> Void
    var onDelete: () -> Void

    @State private var text = ""
    @State private var hovering = false
    @FocusState private var focused: Bool

    var body: some View {
        HStack(spacing: 12) {
            TextField("Rule", text: $text, axis: .vertical)
                .labelsHidden()
                .textFieldStyle(.plain)
                .foregroundStyle(rule.enabled ? .primary : .secondary)
                .focused($focused)
                .onSubmit(commit)
                .onChange(of: focused) { _, f in if !f { commit() } }
            AppScopePicker(app: Binding(get: { rule.app }, set: onApp))
            HoverDeleteButton(visible: hovering, help: "Delete Rule", action: onDelete)
            Toggle("Follow this rule", isOn: Binding(get: { rule.enabled }, set: onToggle))
                .labelsHidden().toggleStyle(.vox)
        }
        .onHover { hovering = $0 }
        .onAppear { text = rule.text }
        .onChange(of: rule.text) { _, t in if !focused { text = t } }
        .contextMenu {
            Button("Edit") { focused = true }
            Button(rule.enabled ? "Turn Off" : "Turn On") { onToggle(!rule.enabled) }
            Divider()
            Button("Delete…", role: .destructive, action: onDelete)
        }
    }

    private func commit() {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if t.isEmpty { text = rule.text; return }
        if t != rule.text { onCommit(t) }
    }
}


/// "Everywhere" or one app: a rule scoped to an app only reaches the prompt while that app is in front.
private struct AppScopePicker: View {
    @Binding var app: String?

    private var apps: [String] {
        let running = NSWorkspace.shared.runningApplications
            .filter { $0.activationPolicy == .regular }
            .compactMap(\.localizedName)
            .filter { $0 != "Vox" }
        return Array(Set(running + (app.map { [$0] } ?? []))).sorted()
    }

    var body: some View {
        Menu {
            Button("Everywhere") { app = nil }
            Divider()
            ForEach(apps, id: \.self) { a in Button(a) { app = a } }
        } label: {
            Text(app ?? "Everywhere")
                .font(.caption.weight(.medium))
                .foregroundStyle(app == nil ? Color.secondary : Color.accentColor)
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .help(app == nil ? "Applies in every app" : "Only applies while \(app!) is in front")
    }
}
