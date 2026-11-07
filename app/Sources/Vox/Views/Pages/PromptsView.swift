import SwiftUI

/// Teach Vox → Prompts: every prompt Vox sends to its brains, readable and editable. "Last sent"
/// shows exactly what went to the model, with the dynamic parts (your rules, notes for the app in
/// front, the clock, the screen state) filled in. Vox itself can't change these; only you can.
struct PromptsView: View {
    @Environment(AppModel.self) private var model
    @State private var prompts: [PromptInfo] = []
    @State private var selected: String?
    @State private var tab: Tab = .prompt
    @State private var draft = ""
    @State private var recent: [SentPrompt] = []
    @State private var error: String?
    @State private var saving = false
    @State private var confirmReset = false

    enum Tab: String, CaseIterable, Identifiable { case prompt = "Prompt", sent = "Last Sent"; var id: String { rawValue } }

    private var current: PromptInfo? { prompts.first { $0.name == selected } }

    var body: some View {
        RequiresEngine {
            HStack(spacing: 0) {
                List(selection: $selected) {
                    ForEach(prompts) { p in
                        VStack(alignment: .leading, spacing: 2) {
                            HStack(spacing: 6) {
                                Text(p.title).font(.body.weight(.medium))
                                if p.edited {
                                    Text("Edited").font(.caption2.weight(.semibold)).foregroundStyle(.orange)
                                        .padding(.horizontal, 5).padding(.vertical, 1)
                                        .background(.orange.opacity(0.12), in: Capsule())
                                }
                            }
                            Text(p.description).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                        }
                        .padding(.vertical, 4)
                        .tag(p.name)
                    }
                }
                .listStyle(.sidebar)
                .frame(width: 260)

                Divider()

                if let p = current {
                    VStack(alignment: .leading, spacing: 12) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(p.title).font(.title2.weight(.semibold))
                            Text(p.description).foregroundStyle(.secondary)
                            if p.usesCore == true {
                                Label("Sent with \u{201C}Core: what Vox is\u{201D} above it.", systemImage: "square.stack")
                                    .font(.callout).foregroundStyle(.secondary)
                            }
                        }
                        Picker("", selection: $tab) {
                            ForEach(Tab.allCases) { Text($0.rawValue).tag($0) }
                        }
                        .pickerStyle(.segmented).labelsHidden().fixedSize()
                        if let error {
                            Label(error, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red).font(.callout)
                        }
                        if tab == .prompt { editor(p) } else { sent }
                    }
                    .padding(Metrics.page)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                } else {
                    ContentUnavailableView("Choose a prompt", systemImage: "text.alignleft",
                                           description: Text("Pick one on the left to read or edit it."))
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .task { await load() }
            .onChange(of: selected) { _, _ in
                draft = current?.text ?? ""
                error = nil
                Task { await loadRecent() }
            }
            .onChange(of: tab) { _, t in if t == .sent { Task { await loadRecent() } } }
        }
    }

    private func editor(_ p: PromptInfo) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            TextEditor(text: $draft)
                .font(.system(.callout, design: .monospaced))
                .scrollContentBackground(.hidden)
                .padding(8)
                .background(.background.secondary, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).strokeBorder(.separator))
            HStack {
                Text(draft == p.text ? "\(draft.count) characters" : "Unsaved changes")
                    .font(.caption).foregroundStyle(draft == p.text ? Color.secondary : Color.orange)
                Spacer()
                if p.edited {
                    Button("Reset to Default…") { confirmReset = true }
                        .confirmationDialog("Reset \u{201C}\(p.title)\u{201D} to Vox's default?", isPresented: $confirmReset) {
                            Button("Reset", role: .destructive) { Task { await reset(p) } }
                        } message: { Text("Your edits to this prompt will be lost.") }
                }
                Button("Revert") { draft = p.text }.disabled(draft == p.text)
                Button(saving ? "Saving…" : "Save") { Task { await save(p) } }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut("s", modifiers: .command)
                    .disabled(draft == p.text || saving)
            }
        }
    }

    private var sent: some View {
        Group {
            if recent.isEmpty {
                ContentUnavailableView("Nothing sent yet", systemImage: "paperplane",
                                       description: Text("Use Vox and the last few times this prompt was sent appear here, exactly as the model got them."))
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        ForEach(recent) { r in SentCard(sent: r) }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    }

    // MARK: Data

    private func load() async {
        do {
            prompts = try await model.api.get("prompts")
            if selected == nil { selected = prompts.first?.name }
            draft = current?.text ?? ""
            error = nil
        } catch { self.error = "Couldn't load the prompts. Is Vox running?" }
    }

    private func loadRecent() async {
        guard let name = selected else { return }
        recent = (try? await model.api.get("prompts/recent?prompt=\(name)&limit=8")) ?? []
    }

    private func save(_ p: PromptInfo) async {
        saving = true
        defer { saving = false }
        do {
            let updated: PromptInfo = try await model.api.send("prompts/\(p.name)", method: "PUT", body: ["text": draft])
            replace(updated)
        } catch { self.error = "Couldn't save: \(error.localizedDescription)" }
    }

    private func reset(_ p: PromptInfo) async {
        do {
            let updated: PromptInfo = try await model.api.send("prompts/\(p.name)", method: "DELETE", body: Optional<[String: String]>.none)
            replace(updated)
            draft = updated.text
        } catch { self.error = "Couldn't reset: \(error.localizedDescription)" }
    }

    private func replace(_ p: PromptInfo) {
        if let i = prompts.firstIndex(where: { $0.name == p.name }) { prompts[i] = p }
    }
}

private struct SentCard: View {
    var sent: SentPrompt
    @State private var showSystem = false

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text(ISO8601.parse(sent.ts)?.friendly ?? sent.ts).font(.caption.weight(.semibold))
                    Text("\(sent.brain) brain · \(BrainNames.model(sent.model))").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                }
                labelled("Message", sent.message)
                labelled("Reply", sent.reply)
                DisclosureGroup("Full system prompt (\(sent.system.count) characters)", isExpanded: $showSystem) {
                    Text(sent.system).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading).padding(.top, 4)
                }
                .font(.caption)
            }
        }
    }

    private func labelled(_ title: String, _ text: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(text).font(.system(.callout, design: .monospaced)).textSelection(.enabled).lineLimit(8)
        }
    }
}

struct PromptInfo: Codable, Identifiable, Hashable {
    var name: String
    var title: String
    var description: String
    var text: String
    var `default`: String
    var edited: Bool
    var usesCore: Bool?
    var id: String { name }
}

struct SentPrompt: Codable, Identifiable, Hashable {
    var ts: String
    var prompt: String
    var brain: String
    var model: String
    var system: String
    var message: String
    var reply: String
    var id: String { ts + prompt + String(message.prefix(20)) }
}
