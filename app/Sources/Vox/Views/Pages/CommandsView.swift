import SwiftUI

/// What you can say to Vox, by where it works, plus a review of what Vox has learned on its own.
struct CommandsView: View {
    enum Tab: String { case all, learning }

    @Environment(AppModel.self) private var model
    @State private var store = CommandsStore()
    @State private var tab: Tab = .all
    @State private var search = ""

    var body: some View {
        RequiresEngine {
            Group {
                if store.loaded {
                    if tab == .all {
                        CommandList(store: store, search: search)
                    } else {
                        LearningReview(store: store, search: search)
                    }
                } else if let loadError = store.loadError {
                    LoadErrorView(title: "Couldn't load commands", message: loadError) { Task { await store.load() } }
                } else {
                    PageLoading()
                }
            }
            .pageErrors($store.error, loadError: $store.loadError, loaded: store.loaded)
            .refreshesPage {
                store.api = model.api
                await store.load()
            }
            .searchable(text: $search, prompt: tab == .all ? "Search commands" : "Search what Vox learned")
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Picker("Show", selection: $tab) {
                        Text("All Commands").tag(Tab.all)
                        Text(store.suggestions.isEmpty ? "Learning" : "Learning (\(store.suggestions.count))").tag(Tab.learning)
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    .fixedSize()
                }
            }
        }
    }
}

// MARK: Store

/// Both tabs read and change the same command data, so it lives in one place.
@MainActor
@Observable
final class CommandsStore {
    var api = APIClient()
    var contexts: [CommandContext] = []
    var learning = LearningView(mode: "off", aliases: [], learned: [], candidates: [])
    var loaded = false
    /// The latest change that failed, and the latest load that failed.
    var error: String?
    var loadError: String?

    var suggestions: [LearningCandidate] { learning.candidates.filter { !$0.blocked } }

    func load() async {
        do {
            async let db: CommandDb = api.get("commands")
            async let lv: LearningView = api.get("commands/learning")
            (contexts, learning) = try await (db.contexts, lv)
            loaded = true
            loadError = nil
        } catch {
            loadError = ErrorWords.reason(error)
        }
    }

    func command(_ id: Int) -> (CommandContext, Command)? {
        for c in contexts { if let m = c.commands.first(where: { $0.id == id }) { return (c, m) } }
        return nil
    }

    func setContextEnabled(_ id: Int, _ on: Bool) {
        guard let i = contexts.firstIndex(where: { $0.id == id }) else { return }
        contexts[i].enabled = on
        send("Couldn't change that.") { try await self.api.patch("commands/contexts/\(id)", ["enabled": .bool(on)]) }
    }

    func setCommandEnabled(_ id: Int, _ on: Bool) {
        editCommand(id) { $0.enabled = on }
        send("Couldn't change that command.") { try await self.api.patch("commands/\(id)", ["enabled": .bool(on)]) }
    }

    /// Adds a way of saying a command. Returns an error message, or nil on success.
    func addPhrase(_ commandId: Int, _ text: String) async -> String? {
        do {
            let p: CommandPhrase = try await api.send("commands/\(commandId)/phrases", method: "POST",
                                                      body: ["text": JSONValue.string(text)])
            editCommand(commandId) { cmd in if !cmd.phrases.contains(where: { $0.id == p.id }) { cmd.phrases.append(p) } }
            return nil
        } catch {
            return ErrorWords.message("Couldn't add that phrase.", error)
        }
    }

    func removePhrase(_ phraseId: Int, from commandId: Int) {
        editCommand(commandId) { $0.phrases.removeAll { $0.id == phraseId } }
        learning.aliases?.removeAll { $0.id == phraseId }
        send("Couldn't remove that phrase.") { try await self.api.delete("commands/phrases/\(phraseId)") }
    }

    func approve(_ c: LearningCandidate) {
        learning.candidates.removeAll { $0.id == c.id }
        send("Couldn't approve that suggestion.", reloadAfter: true) { try await self.api.post("commands/candidates/\(c.id)/promote") }
    }

    func reject(_ c: LearningCandidate) {
        if let i = learning.candidates.firstIndex(where: { $0.id == c.id }) { learning.candidates[i].blocked = true }
        send("Couldn't reject that suggestion.") { try await self.api.post("commands/candidates/\(c.id)/reject") }
    }

    func forget(_ id: Int) {
        learning.learned.removeAll { $0.id == id }
        for i in contexts.indices { contexts[i].commands.removeAll { $0.id == id } }
        send("Couldn't forget that command.") { try await self.api.delete("commands/learned/\(id)") }
    }

    private func editCommand(_ id: Int, _ change: (inout Command) -> Void) {
        for i in contexts.indices {
            if let j = contexts[i].commands.firstIndex(where: { $0.id == id }) { change(&contexts[i].commands[j]); return }
        }
    }

    /// Persist an optimistic change; re-read on failure so the page never lies.
    private func send(_ failure: String, reloadAfter: Bool = false, _ op: @escaping () async throws -> Void) {
        Task {
            do { try await op(); if reloadAfter { await load() } }
            catch { self.error = ErrorWords.message(failure, error); await load() }
        }
    }
}

// MARK: Words

/// Plain-English descriptions of what a command does, for places that only have the raw action.
enum CommandWords {
    static func describe(_ intent: String, _ arg: String?) -> String {
        let a = (arg ?? "").trimmingCharacters(in: .whitespaces)
        let quoted = "\u{201C}\(a)\u{201D}"
        switch intent {
        case "navigate": return a.isEmpty ? "Open an app or website" : "Open \(a.capitalized)"
        case "navigate_new": return "Open \(a.capitalized) in a new tab"
        case "app_cycle": return "Switch to \(a.capitalized)"
        case "click": return "Click \(quoted)"
        case "tab": return "Switch to the \(quoted) tab"
        case "window": return "Switch to the \(quoted) window"
        case "search": return "Search the web for \(quoted)"
        case "tab_index": return "Go to tab \(a)"
        case "window_index": return "Go to window \(a)"
        case "desktop_index": return "Go to desktop \(a)"
        case "profile": return "Switch to profile \(a)"
        case "close_tab": return "Close the tab"
        case "reload": return "Reload the page"
        case "back": return "Go back"
        default:
            let words = intent.replacingOccurrences(of: "_", with: " ").capitalized
            return a.isEmpty ? words : "\(words) \(quoted)"
        }
    }

    /// A command's name for people. Learned commands arrive with a raw label ("Learned: tab gmail"),
    /// so those are described from what they do instead.
    static func title(label: String, intent: String, arg: String?) -> String {
        label.isEmpty || label.hasPrefix("Learned:") ? describe(intent, arg) : label
    }

    /// "Everywhere" or "In Spotify", from the learning API's context name.
    static func place(_ context: String) -> String {
        context == "global" || context == "Everywhere" ? "Everywhere" : "In \(context)"
    }

    static func quoted(_ phrases: [String]) -> String {
        phrases.map { "\u{201C}\($0)\u{201D}" }.joined(separator: "  ")
    }
}

// MARK: All commands

private struct CommandList: View {
    var store: CommandsStore
    var search: String
    @State private var editing: EditTarget?

    private struct EditTarget: Identifiable { var id: Int }

    private var query: String { search.trimmingCharacters(in: .whitespaces).lowercased() }

    /// Searches what the rows show: the command's title, its phrases, and where it works.
    private func matches(_ c: Command, in ctx: CommandContext) -> Bool {
        query.isEmpty
            || CommandWords.title(label: c.label, intent: c.intent, arg: c.arg).lowercased().contains(query)
            || c.phrases.contains { $0.text.lowercased().contains(query) }
            || ctx.displayName.lowercased().contains(query)
    }

    var body: some View {
        let groups = store.contexts.compactMap { ctx -> (CommandContext, [Command])? in
            let cmds = ctx.commands.filter { matches($0, in: ctx) }
            return cmds.isEmpty ? nil : (ctx, cmds)
        }
        Group {
            if groups.isEmpty {
                if query.isEmpty {
                    ContentUnavailableView("No commands", systemImage: "command",
                                           description: Text("Vox's commands will appear here once its command list is set up."))
                } else {
                    ContentUnavailableView.search(text: search)
                }
            } else {
                Form {
                    ForEach(groups, id: \.0.id) { ctx, cmds in
                        Section {
                            ContextRow(context: ctx, count: ctx.commands.count) { store.setContextEnabled(ctx.id, $0) }
                            ForEach(cmds) { cmd in
                                CommandRow(command: cmd, contextOn: ctx.enabled,
                                           onToggle: { store.setCommandEnabled(cmd.id, $0) },
                                           onEdit: { editing = EditTarget(id: cmd.id) },
                                           onForget: { store.forget(cmd.id) })
                            }
                        }
                    }
                }
                .formStyle(.grouped)
            }
        }
        .sheet(item: $editing) { target in PhraseEditor(store: store, commandId: target.id) }
    }
}

/// The first row of each group: where these commands work, with one switch for all of them.
private struct ContextRow: View {
    var context: CommandContext
    var count: Int
    var onToggle: (Bool) -> Void

    var body: some View {
        HStack(spacing: 12) {
            ContextIcon(context: context)
            VStack(alignment: .leading, spacing: 2) {
                Text(context.displayName).font(.headline)
                Text(subtitle).font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 12)
            Toggle("Use commands in \(context.displayName)", isOn: Binding(get: { context.enabled }, set: onToggle))
                .labelsHidden().toggleStyle(.switch).controlSize(.small)
                .help(context.enabled ? "Turn off every command in this group" : "Turn this group back on")
        }
        .padding(.vertical, 2)
    }

    private var subtitle: String {
        let n = count == 1 ? "1 command" : "\(count) commands"
        switch context.kind {
        case "global": return "\(n) · work in any app"
        case "site": return "\(n) · only on \(context.matchValue ?? context.displayName)"
        default: return "\(n) · only when \(context.displayName) is in front"
        }
    }
}

private struct ContextIcon: View {
    var context: CommandContext

    var body: some View {
        Group {
            if context.kind == "app", let icon = AppIcons.icon(for: context.matchValue ?? context.displayName) {
                Image(nsImage: icon).resizable().interpolation(.high)
            } else {
                Image(systemName: context.kind == "global" ? "globe" : context.kind == "site" ? "safari" : "app.dashed")
                    .font(.system(size: 15, weight: .medium))
                    .foregroundStyle(.white)
                    .frame(width: 24, height: 24)
                    .background(context.kind == "global" ? Color.blue.gradient : Color.gray.gradient,
                                in: RoundedRectangle(cornerRadius: 6, style: .continuous))
            }
        }
        .frame(width: ContextIcon.size, height: ContextIcon.size)
    }

    static let size: CGFloat = 28
}

private struct CommandRow: View {
    var command: Command
    var contextOn: Bool
    var onToggle: (Bool) -> Void
    var onEdit: () -> Void
    var onForget: () -> Void

    @State private var hovering = false
    @State private var confirmForget = false

    private var learned: Bool { command.source == "learned" }
    private var title: String { CommandWords.title(label: command.label, intent: command.intent, arg: command.arg) }
    private var active: Bool { command.enabled && contextOn }

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(title)
                    if learned { SourceTag(text: "Learned", symbol: "sparkles", color: .purple) }
                    else if command.source == "user" { SourceTag(text: "Added by you", symbol: "person.fill", color: .blue) }
                }
                Text(CommandWords.quoted(command.phrases.map(\.text)))
                    .font(.callout).foregroundStyle(.secondary).lineLimit(2)
            }
            .opacity(active ? 1 : 0.55)

            Spacer(minLength: 12)
            Button("Edit Phrases", systemImage: "info.circle", action: onEdit)
                .labelStyle(.iconOnly).buttonStyle(.borderless).foregroundStyle(.secondary)
                .opacity(hovering ? 1 : 0)
                .help("See and change what you can say")
            Toggle("Use \(title)", isOn: Binding(get: { command.enabled }, set: onToggle))
                .labelsHidden().toggleStyle(.switch).controlSize(.small)
                .disabled(!contextOn)
        }
        .contentShape(Rectangle())
        .onHover { hovering = $0 }
        .onTapGesture(count: 2, perform: onEdit)
        .help(learned ? "Vox learned this from you" : command.source == "user" ? "You added this" : "Built into Vox")
        .contextMenu {
            Button("Edit Phrases…", action: onEdit)
            Button(command.enabled ? "Turn Off" : "Turn On") { onToggle(!command.enabled) }
            if learned {
                Divider()
                Button("Forget This Command…", role: .destructive) { confirmForget = true }
            }
        }
        .confirmationDialog("Forget \u{201C}\(title)\u{201D}?", isPresented: $confirmForget, titleVisibility: .visible) {
            Button("Forget Command", role: .destructive, action: onForget)
        } message: {
            Text("Vox will stop using it, and won't learn it again for a while.")
        }
    }
}

struct SourceTag: View {
    var text: String
    var symbol: String?
    var color: Color
    var body: some View {
        HStack(spacing: 3) {
            if let symbol { Image(systemName: symbol) }
            Text(text)
        }
        .font(.caption2.weight(.semibold))
        .foregroundStyle(color)
        .padding(.horizontal, 6).padding(.vertical, 1.5)
        .background(color.opacity(0.13), in: Capsule())
    }
}

// MARK: Phrase editor

/// Phrases save as you go. Return adds the phrase you typed; ⌘Return or Done adds anything still
/// typed and closes; Escape closes without adding it.
private struct PhraseEditor: View {
    var store: CommandsStore
    var commandId: Int

    @Environment(\.dismiss) private var dismiss
    @State private var draft = ""
    @State private var error: String?
    @State private var adding = false
    @FocusState private var fieldFocused: Bool

    private var pending: String { draft.trimmingCharacters(in: .whitespaces) }

    var body: some View {
        VStack(spacing: 0) {
            if let found = store.command(commandId) {
                let (ctx, cmd) = found
                VStack(spacing: 2) {
                    Text(CommandWords.title(label: cmd.label, intent: cmd.intent, arg: cmd.arg)).font(.headline)
                    Text(ctx.kind == "global" ? "Works everywhere" : "Works in \(ctx.displayName)")
                        .font(.callout).foregroundStyle(.secondary)
                }
                .padding(.top, Metrics.gap + 4)
                Form {
                    Section {
                        ForEach(cmd.phrases) { p in
                            HStack(spacing: 8) {
                                Text("\u{201C}\(p.text)\u{201D}")
                                if p.isPrimary { SourceTag(text: "Main", color: .secondary) }
                                if p.matchType == "exact" { SourceTag(text: "Exact match", color: .secondary) }
                                Spacer()
                                Button("Remove", systemImage: "minus.circle.fill") { store.removePhrase(p.id, from: cmd.id) }
                                    .labelStyle(.iconOnly).buttonStyle(.borderless)
                                    .foregroundStyle(cmd.phrases.count > 1 ? Color.red : Color.secondary)
                                    .disabled(cmd.phrases.count <= 1)
                                    .help(cmd.phrases.count > 1 ? "Remove this phrase" : "A command needs at least one phrase")
                            }
                        }
                        HStack(spacing: 8) {
                            TextField("Another way to say it", text: $draft, prompt: Text("Add another way to say it"))
                                .labelsHidden().textFieldStyle(.plain)
                                .focused($fieldFocused)
                                .onSubmit { add(cmd.id) }
                            Button("Add") { add(cmd.id) }
                                .disabled(pending.isEmpty || adding)
                        }
                    } header: {
                        Text("You can say")
                    } footer: {
                        if let error {
                            ErrorBanner(message: error)
                        } else {
                            Text(cmd.phrases.contains { $0.matchType == "exact" }
                                 ? "Vox runs this command when it hears any of these, even inside a longer sentence. Exact matches only count when said on their own."
                                 : "Vox runs this command when it hears any of these, even inside a longer sentence.")
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                .formStyle(.grouped)
            } else {
                ContentUnavailableView("This command is gone", systemImage: "questionmark.circle")
            }
            Divider()
            HStack {
                Spacer()
                Button("Done", action: done)
                    .keyboardShortcut(.return, modifiers: .command)
                    .buttonStyle(.borderedProminent)
                    .disabled(adding)
                    .help("Close (⌘Return)")
            }
            .padding(Metrics.gap)
            .background {
                // Escape closes. A sheet only hears Escape through a cancel button, and there's
                // nothing to cancel here: every phrase is already saved.
                Button("Close") { dismiss() }.keyboardShortcut(.cancelAction).opacity(0).accessibilityHidden(true)
            }
        }
        .frame(width: 460, height: 440)
        .onAppear { fieldFocused = true }
    }

    private func add(_ id: Int) {
        Task { await addPending(id) }
    }

    /// Adds what's typed, if anything. Returns false when that failed.
    @discardableResult
    private func addPending(_ id: Int) async -> Bool {
        let t = pending
        guard !t.isEmpty, !adding else { return true }
        adding = true
        error = await store.addPhrase(id, t)
        if error == nil { draft = "" }
        adding = false
        fieldFocused = true
        return error == nil
    }

    /// Done keeps a phrase that was typed but not added yet, then closes.
    private func done() {
        Task {
            guard let (_, cmd) = store.command(commandId) else { dismiss(); return }
            if await addPending(cmd.id) { dismiss() }
        }
    }
}
