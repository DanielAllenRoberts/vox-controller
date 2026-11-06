import AppKit
import SwiftUI

/// Everything Vox remembers about you, in the open: long-term facts it always keeps in mind, and the
/// day-by-day notes it jots down. You can read, correct, add and forget any of it.
struct MemoryView: View {
    @Environment(AppModel.self) private var model
    @State private var core: [Memory]?
    @State private var dates: [String] = []
    @State private var day = ""
    @State private var daily: [Memory] = []
    @State private var everything: [Memory]?
    @State private var query = ""
    @State private var error: String?
    @State private var loadError: String?
    @State private var selection = Set<String>()
    @State private var editing: Memory?
    @State private var adding = false
    @State private var forgetting: [Memory] = []

    var body: some View {
        RequiresEngine {
            content
                .pageErrors($error, loadError: $loadError, loaded: core != nil)
                .refreshesPage(reloadAll)
                .searchable(text: $query, prompt: "Search memories")
                .toolbar {
                    ToolbarItemGroup(placement: .primaryAction) {
                        Button("Show in Finder", systemImage: "folder") { reveal() }
                            .help("Show the memory files in Finder. They're plain text you can read.")
                        Button("Add Memory", systemImage: "plus") { adding = true }
                            .help("Tell Vox something to remember")
                    }
                }
                .task(id: day) { await loadDay() }
                .task(id: query.isEmpty) { if !query.isEmpty { await loadEverything() } }
                .sheet(isPresented: $adding) {
                    MemoryEditor(memory: nil) { text, tier in Task { await add(text, tier: tier) } }
                }
                .sheet(item: $editing) { m in
                    MemoryEditor(memory: m) { text, _ in Task { await update(m, text: text) } }
                }
                .confirmationDialog(forgetTitle, isPresented: .init(get: { !forgetting.isEmpty }, set: { if !$0 { forgetting = [] } }),
                                    titleVisibility: .visible) {
                    Button("Forget", role: .destructive) { let f = forgetting; Task { await forget(f) } }
                } message: {
                    Text(forgetting.count == 1 ? "\u{201C}\(forgetting[0].text)\u{201D}\n\nVox won't remember this any more."
                                               : "Vox won't remember these any more.")
                }
        }
    }

    private var forgetTitle: String { forgetting.count > 1 ? "Forget \(forgetting.count) memories?" : "Forget this memory?" }

    // MARK: Content

    @ViewBuilder
    private var content: some View {
        if let core {
            if core.isEmpty && dates.isEmpty && query.isEmpty {
                ContentUnavailableView {
                    Label("Vox doesn't remember anything yet", systemImage: "brain")
                } description: {
                    Text("Say \u{201C}Remember that I take my coffee black,\u{201D} or add something here.")
                } actions: {
                    Button("Add Memory") { adding = true }
                }
            } else {
                list(core)
            }
        } else if let loadError {
            LoadErrorView(title: "Couldn't load memories", message: loadError) { Task { await reloadAll() } }
        } else {
            PageLoading()
        }
    }

    private func list(_ core: [Memory]) -> some View {
        let searching = !query.trimmingCharacters(in: .whitespaces).isEmpty
        let longTerm = searching ? matches(everything?.filter { $0.tier == "core" } ?? core) : core
        let notes = searching ? matches(everything?.filter { $0.tier != "core" } ?? []) : daily
        let visible = longTerm + notes

        return List(selection: $selection) {
            Section {
                if longTerm.isEmpty {
                    Placeholder(text: searching ? "No matches." : "Nothing yet. Long-term facts appear here.")
                }
                ForEach(longTerm) { m in MemoryRow(memory: m, showDate: false).tag(m.id) }
            } header: {
                SectionHeader(title: "Long-term", detail: searching ? nil : "Vox keeps these in mind in every conversation.")
            }

            Section {
                if notes.isEmpty {
                    Placeholder(text: searching ? "No matches." : "No notes on this day.")
                }
                ForEach(notes) { m in MemoryRow(memory: m, showDate: searching).tag(m.id) }
            } header: {
                HStack(alignment: .firstTextBaseline) {
                    SectionHeader(title: searching ? "Daily notes" : "Daily notes · \(Self.dayTitle(day))",
                                  detail: searching ? nil : "Notes from a single day. Vox recalls today's and yesterday's on its own, and older ones when they're relevant.")
                    Spacer(minLength: 12)
                    if !searching && !dates.isEmpty { DayPicker(dates: dates, day: $day) }
                }
            }
        }
        .listStyle(.inset)
        .contextMenu(forSelectionType: String.self) { ids in
            let picked = visible.filter { ids.contains($0.id) }
            if picked.count == 1 {
                Button("Edit…") { editing = picked[0] }
                Button("Copy") { copy(picked[0].text) }
                Divider()
            }
            if !picked.isEmpty {
                Button(picked.count == 1 ? "Forget…" : "Forget \(picked.count) Memories…", role: .destructive) { forgetting = picked }
            }
        } primaryAction: { ids in
            if ids.count == 1, let m = visible.first(where: { ids.contains($0.id) }) { editing = m }
        }
        .onDeleteCommand { forgetting = visible.filter { selection.contains($0.id) } }
    }

    private func matches(_ items: [Memory]) -> [Memory] {
        let q = query.trimmingCharacters(in: .whitespaces)
        return items.filter { m in
            m.text.localizedCaseInsensitiveContains(q) || m.tags.contains { $0.localizedCaseInsensitiveContains(q) }
        }
    }

    /// "Today", "Yesterday", or "Friday 19 June".
    static func dayTitle(_ day: String) -> String {
        guard let d = LocalISO.day(day) else { return "Today" }
        if Calendar.current.isDateInToday(d) { return "Today" }
        if Calendar.current.isDateInYesterday(d) { return "Yesterday" }
        return d.formatted(.dateTime.weekday(.wide).day().month(.wide))
    }

    // MARK: Data

    private func load() async {
        do {
            async let c: [Memory] = model.api.get("memory/core")
            async let d: [String] = model.api.get("memory/dates")
            let (cs, ds) = try await (c, d)
            core = cs
            dates = ds
            if day.isEmpty || !ds.contains(day) { day = ds.first ?? LocalISO.string(.now).prefix(10).description }
            loadError = nil
        } catch { loadError = ErrorWords.reason(error) }
        if !query.isEmpty { await loadEverything() }
    }

    private func loadDay() async {
        guard !day.isEmpty else { return }
        do { daily = try await model.api.get("memory/daily?date=\(day)") }
        catch { loadError = ErrorWords.reason(error) }
    }

    /// Search reads every memory across all days (limit=0 means "all").
    private func loadEverything() async {
        do { everything = try await model.api.get("memory?limit=0") }
        catch { loadError = ErrorWords.reason(error) }
    }

    private func reloadAll() async {
        await load()
        await loadDay()
    }

    private func add(_ text: String, tier: String) async {
        do { try await model.api.send("memory", MemoryAddBody(text: text, tier: tier)); error = nil }
        catch { self.error = ErrorWords.message("Couldn't save that memory.", error) }
        if tier == "daily" { day = LocalISO.string(.now).prefix(10).description }
        await reloadAll()
    }

    private func update(_ m: Memory, text: String) async {
        replace(m.id) { $0.text = text }
        do { try await model.api.patch("memory/\(m.id)", ["text": .string(text)]); error = nil }
        catch { self.error = ErrorWords.message("Couldn't save that change.", error) }
        await reloadAll()
    }

    private func forget(_ items: [Memory]) async {
        let ids = Set(items.map(\.id))
        withAnimation(.smooth) {
            core?.removeAll { ids.contains($0.id) }
            daily.removeAll { ids.contains($0.id) }
            everything?.removeAll { ids.contains($0.id) }
        }
        selection.subtract(ids)
        do {
            for id in ids { try await model.api.delete("memory/\(id)") }
            error = nil
        } catch { self.error = ErrorWords.message("Couldn't forget that.", error) }
        await reloadAll()
    }

    /// Optimistic in-place edit across whichever lists hold the entry.
    private func replace(_ id: String, _ change: (inout Memory) -> Void) {
        if let i = core?.firstIndex(where: { $0.id == id }) { change(&core![i]) }
        if let i = daily.firstIndex(where: { $0.id == id }) { change(&daily[i]) }
        if let i = everything?.firstIndex(where: { $0.id == id }) { change(&everything![i]) }
    }

    /// The engine answers `{ok: false}` with a 200 when Finder couldn't be opened, so check the body.
    private func reveal() {
        Task {
            let failed = "Couldn't show the memory files in Finder."
            do {
                let r: [String: JSONValue] = try await model.api.send("memory/reveal", method: "POST", body: [String: JSONValue]())
                if r["ok"]?.bool == false { error = failed }
            } catch { self.error = ErrorWords.message(failed, error) }
        }
    }

    private func copy(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }
}

// MARK: Rows

private struct MemoryRow: View {
    var memory: Memory
    var showDate: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(memory.text).lineLimit(nil).fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 6) {
                if let d = ISO8601.parse(memory.ts) {
                    Text(showDate ? d.formatted(date: .abbreviated, time: .shortened) : "Added \(d.formatted(.dateTime.day().month(.abbreviated).year()))")
                }
                ForEach(memory.tags, id: \.self) { t in
                    Text(t).padding(.horizontal, 6).padding(.vertical, 1).background(.quaternary, in: Capsule())
                }
            }
            .font(.caption).foregroundStyle(.secondary)
        }
        .padding(.vertical, 3)
    }
}

private struct SectionHeader: View {
    var title: String
    var detail: String?
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).pageSectionHeader()
            if let detail { Text(detail).font(.callout).fontWeight(.regular).foregroundStyle(.secondary) }
        }
        .padding(.top, 6)
    }
}

private struct Placeholder: View {
    var text: String
    var body: some View {
        Text(text).foregroundStyle(.secondary).selectionDisabled()
    }
}

/// Step between days that have notes, newest first, plus a menu of every day.
private struct DayPicker: View {
    var dates: [String]
    @Binding var day: String

    private var index: Int? { dates.firstIndex(of: day) }

    var body: some View {
        HStack(spacing: 2) {
            Button { step(1) } label: { Image(systemName: "chevron.left") }
                .disabled((index ?? dates.count) >= dates.count - 1)
                .help("Earlier day")
                .accessibilityLabel("Earlier day")
            Menu {
                Picker("Day", selection: $day) {
                    ForEach(dates, id: \.self) { d in Text(MemoryView.dayTitle(d)).tag(d) }
                }
                .pickerStyle(.inline)
            } label: {
                Image(systemName: "calendar")
            }
            .menuIndicator(.hidden)
            .fixedSize()
            .help("Choose a day")
            .accessibilityLabel("Choose a day")
            Button { step(-1) } label: { Image(systemName: "chevron.right") }
                .disabled((index ?? 0) <= 0)
                .help("Later day")
                .accessibilityLabel("Later day")
        }
        .buttonStyle(.borderless)
        .font(.callout)
    }

    private func step(_ by: Int) {
        guard let i = index, dates.indices.contains(i + by) else { return }
        day = dates[i + by]
    }
}

// MARK: Editor

private struct MemoryEditor: View {
    var memory: Memory?
    var onSave: (_ text: String, _ tier: String) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var text: String
    @State private var tier = "core"

    init(memory: Memory?, onSave: @escaping (String, String) -> Void) {
        self.memory = memory
        self.onSave = onSave
        _text = State(initialValue: memory?.text ?? "")
    }

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        Form {
            Section {
                TextField("Memory", text: $text, prompt: Text("I take my coffee black"), axis: .vertical)
                    .labelsHidden()
                    .lineLimit(3...10)
            } header: {
                Text(memory == nil ? "What should Vox remember?" : "Correct what Vox remembers")
            }
            if memory == nil {
                Section {
                    Picker("Keep it", selection: $tier) {
                        Text("Long-term, in every conversation").tag("core")
                        Text("In today's notes").tag("daily")
                    }
                    .pickerStyle(.radioGroup)
                }
            }
        }
        .formStyle(.grouped)
        .frame(width: 460)
        .fixedSize(horizontal: false, vertical: true)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button(memory == nil ? "Remember" : "Save") { onSave(trimmed, tier); dismiss() }
                    .disabled(trimmed.isEmpty || trimmed == memory?.text)
            }
        }
    }
}
