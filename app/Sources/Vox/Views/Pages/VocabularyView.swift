import SwiftUI

/// Speech corrections: "when Vox hears this, write that". Fixes names and words it mishears.
struct VocabularyView: View {
    @Environment(AppModel.self) private var model
    @State private var entries: [VocabEntry] = []
    @State private var loaded = false
    @State private var error: String?
    @State private var heard = ""
    @State private var write = ""
    @State private var pendingDelete: VocabEntry?
    @FocusState private var addFocus: AddField?

    private enum AddField { case heard, write }

    /// Both columns line up across the add row and every entry.
    static let heardWidth: CGFloat = 220

    private var canAdd: Bool { !heard.trimmingCharacters(in: .whitespaces).isEmpty }

    var body: some View {
        RequiresEngine {
            Group {
                if loaded { form } else { PageLoading() }
            }
            .inlineError($error)
            .toolbar {
                ToolbarItem {
                    Button("New Correction", systemImage: "plus") { addFocus = .heard }
                        .help("Add a correction")
                }
            }
            .confirmationDialog("Delete this correction?", isPresented: deleteBinding, titleVisibility: .visible,
                                presenting: pendingDelete) { entry in
                Button("Delete Correction", role: .destructive) { delete(entry) }
            } message: { entry in
                Text("Vox will write \u{201C}\(entry.heard)\u{201D} as it hears it again.")
            }
            .task { await load() }
        }
    }

    private var form: some View {
        Form {
            Section {
                HStack(spacing: 12) {
                    TextField("When Vox hears", text: $heard, prompt: Text("When Vox hears…"))
                        .labelsHidden().textFieldStyle(.plain)
                        .focused($addFocus, equals: .heard)
                        .onSubmit { addFocus = .write }
                        .frame(width: Self.heardWidth)
                    Arrow()
                    TextField("Write", text: $write, prompt: Text("…write this instead"))
                        .labelsHidden().textFieldStyle(.plain)
                        .focused($addFocus, equals: .write)
                        .onSubmit(add)
                    Button("Add", action: add).disabled(!canAdd)
                }
            } footer: {
                Text("Fix words Vox keeps mishearing, like a name it spells wrong. Corrections apply to everything Vox hears, in every mode. Leave the second box empty to drop the word altogether.")
                    .foregroundStyle(.secondary)
            }

            Section {
                if entries.isEmpty {
                    ContentUnavailableView("No corrections yet", systemImage: "character.book.closed",
                                           description: Text("When Vox gets a word wrong, add what it heard and what you meant."))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, Metrics.gap)
                } else {
                    ForEach(entries) { entry in
                        VocabRow(entry: entry,
                                 onToggle: { setEnabled(entry, $0) },
                                 onCommit: { field, value in edit(entry, field, value) },
                                 onDelete: { pendingDelete = entry })
                    }
                }
            } header: {
                if !entries.isEmpty {
                    HStack(spacing: 12) {
                        Text("When Vox hears").frame(width: Self.heardWidth, alignment: .leading)
                        Arrow().hidden()
                        Text("It writes")
                    }
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
        do { entries = try await model.api.get("vocab"); error = nil }
        catch { self.error = "Couldn't load your corrections. \(error.localizedDescription)" }
        loaded = true
    }

    private func add() {
        let h = heard.trimmingCharacters(in: .whitespaces), w = write.trimmingCharacters(in: .whitespaces)
        guard !h.isEmpty else { return }
        heard = ""; write = ""
        addFocus = .heard
        Task {
            do { try await model.api.post("vocab", ["heard": .string(h), "write": .string(w)]); await load() }
            catch { heard = h; write = w; self.error = "Couldn't add that correction. \(error.localizedDescription)" }
        }
    }

    private func setEnabled(_ entry: VocabEntry, _ on: Bool) {
        guard let i = entries.firstIndex(where: { $0.id == entry.id }) else { return }
        entries[i].enabled = on
        send("Couldn't change that correction.") { try await model.api.patch("vocab/\(entry.id)", ["enabled": .bool(on)]) }
    }

    private func edit(_ entry: VocabEntry, _ field: VocabRow.Field, _ value: String) {
        guard let i = entries.firstIndex(where: { $0.id == entry.id }) else { return }
        switch field {
        case .heard: entries[i].heard = value
        case .write: entries[i].write = value
        }
        let key = field == .heard ? "heard" : "write"
        send("Couldn't save that correction.") { try await model.api.patch("vocab/\(entry.id)", [key: .string(value)]) }
    }

    private func delete(_ entry: VocabEntry) {
        withAnimation(.smooth) { entries.removeAll { $0.id == entry.id } }
        send("Couldn't delete that correction.") { try await model.api.delete("vocab/\(entry.id)") }
    }

    /// Persist an optimistic change; re-read on failure so the list never lies.
    private func send(_ failure: String, _ op: @escaping () async throws -> Void) {
        Task {
            do { try await op() }
            catch { self.error = "\(failure) \(error.localizedDescription)"; await load() }
        }
    }
}

private struct Arrow: View {
    var body: some View {
        Image(systemName: "arrow.right").font(.caption.weight(.semibold)).foregroundStyle(.tertiary)
    }
}

private struct VocabRow: View {
    enum Field { case heard, write }

    var entry: VocabEntry
    var onToggle: (Bool) -> Void
    var onCommit: (Field, String) -> Void
    var onDelete: () -> Void

    @State private var heard = ""
    @State private var write = ""
    @State private var hovering = false
    @FocusState private var focus: Field?

    var body: some View {
        HStack(spacing: 12) {
            TextField("When Vox hears", text: $heard)
                .labelsHidden().textFieldStyle(.plain)
                .focused($focus, equals: .heard)
                .frame(width: VocabularyView.heardWidth)
            Arrow()
            TextField("It writes", text: $write, prompt: Text("Nothing (dropped)"))
                .labelsHidden().textFieldStyle(.plain)
                .fontWeight(.medium)
                .focused($focus, equals: .write)
            HoverDeleteButton(visible: hovering, help: "Delete Correction", action: onDelete)
            Toggle("Use this correction", isOn: Binding(get: { entry.enabled }, set: onToggle))
                .labelsHidden().toggleStyle(.switch).controlSize(.small)
        }
        .foregroundStyle(entry.enabled ? .primary : .secondary)
        .onSubmit { commit() }
        .onChange(of: focus) { old, _ in if old != nil { commit() } }
        .onHover { hovering = $0 }
        .onAppear { heard = entry.heard; write = entry.write }
        .onChange(of: entry) { _, e in if focus == nil { heard = e.heard; write = e.write } }
        .contextMenu {
            Button(entry.enabled ? "Turn Off" : "Turn On") { onToggle(!entry.enabled) }
            Divider()
            Button("Delete…", role: .destructive, action: onDelete)
        }
    }

    private func commit() {
        let h = heard.trimmingCharacters(in: .whitespaces), w = write.trimmingCharacters(in: .whitespaces)
        if h.isEmpty { heard = entry.heard } else if h != entry.heard { onCommit(.heard, h) }
        if w != entry.write { onCommit(.write, w) }
    }
}
