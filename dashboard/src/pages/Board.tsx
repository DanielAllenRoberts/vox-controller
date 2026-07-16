import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  Trash2,
  ChevronLeft,
  ChevronRight,
  Tag,
} from "lucide-react";
import { api, type Board as BoardData, type BoardCard } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { FadeIn } from "@/components/animate/FadeIn";
import { Stagger, StaggerItem } from "@/components/animate/Stagger";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/useToast";

const BOARD_KEY = ["board"] as const;

// ---------------------------------------------------------------------------
// Mutations — all refetch the board on success so ordering/columns stay truthy.
// ---------------------------------------------------------------------------

function useBoardMutation<TArgs>(
  fn: (args: TArgs) => Promise<unknown>,
  messages: { error: string; success?: string },
) {
  const qc = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: BOARD_KEY });
      if (messages.success) toast({ variant: "success", title: messages.success });
    },
    onError: () =>
      toast({
        variant: "error",
        title: messages.error,
        description: "Is the bridge running?",
      }),
  });
}

// ---------------------------------------------------------------------------
// A single card — tags, body preview, and hover controls (move ◄ ►, delete).
// ---------------------------------------------------------------------------

function CardTile({
  card,
  canLeft,
  canRight,
  onMove,
  onDelete,
}: {
  card: BoardCard;
  canLeft: boolean;
  canRight: boolean;
  onMove: (dir: -1 | 1) => void;
  onDelete: () => void;
}) {
  return (
    <Card
      glass
      className="group relative overflow-hidden p-3"
    >
      <span
        aria-hidden
        className="pointer-events-none absolute inset-y-0 left-0 w-0.5 bg-brand-gradient opacity-70"
      />
      <p className="pr-6 text-sm font-medium leading-snug text-foreground">
        {card.title}
      </p>
      {card.body && (
        <p className="mt-1 line-clamp-3 whitespace-pre-wrap text-xs text-foreground-secondary">
          {card.body}
        </p>
      )}
      {card.tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {card.tags.map((t) => (
            <Badge
              key={t}
              variant="outline"
              className="px-1.5 py-0 text-[10px] font-normal"
            >
              <Tag className="h-2.5 w-2.5" />
              {t}
            </Badge>
          ))}
        </div>
      )}

      {/* Hover controls */}
      <div className="mt-2 flex items-center justify-between opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
        <div className="flex gap-1">
          <button
            type="button"
            disabled={!canLeft}
            onClick={() => onMove(-1)}
            aria-label="Move left"
            className="flex h-6 w-6 items-center justify-center rounded-md text-foreground-muted transition-colors hover:bg-accent/15 hover:text-accent disabled:pointer-events-none disabled:opacity-30"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            disabled={!canRight}
            onClick={() => onMove(1)}
            aria-label="Move right"
            className="flex h-6 w-6 items-center justify-center rounded-md text-foreground-muted transition-colors hover:bg-accent/15 hover:text-accent disabled:pointer-events-none disabled:opacity-30"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
        <button
          type="button"
          onClick={onDelete}
          aria-label="Delete card"
          className="flex h-6 w-6 items-center justify-center rounded-md text-foreground-muted transition-colors hover:bg-danger/15 hover:text-danger"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// A column — its cards plus an inline "add a card" input at the bottom.
// ---------------------------------------------------------------------------

function Column({
  name,
  cards,
  canLeft,
  canRight,
  onAdd,
  onMove,
  onDelete,
}: {
  name: string;
  cards: BoardCard[];
  canLeft: boolean;
  canRight: boolean;
  onAdd: (title: string) => void;
  onMove: (card: BoardCard, dir: -1 | 1) => void;
  onDelete: (card: BoardCard) => void;
}) {
  const [title, setTitle] = React.useState("");
  const submit = () => {
    const t = title.trim();
    if (!t) return;
    onAdd(t);
    setTitle("");
  };

  return (
    <div className="flex w-72 shrink-0 flex-col">
      <div className="mb-2 flex items-center justify-between px-1">
        <h2 className="text-overline uppercase text-foreground-muted">{name}</h2>
        <span className="text-xs tabular-nums text-foreground-muted">
          {cards.length}
        </span>
      </div>

      <Stagger className="space-y-2">
        {cards.map((c) => (
          <StaggerItem key={c.id}>
            <CardTile
              card={c}
              canLeft={canLeft}
              canRight={canRight}
              onMove={(dir) => onMove(c, dir)}
              onDelete={() => onDelete(c)}
            />
          </StaggerItem>
        ))}
      </Stagger>

      <div className="mt-2 flex gap-1.5">
        <Input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="Add a card…"
          aria-label={`Add a card to ${name}`}
          className="h-8 text-sm"
        />
        <Button
          variant="ghost"
          onClick={submit}
          disabled={!title.trim()}
          aria-label="Add card"
          className="h-8 w-8 shrink-0 p-0"
        >
          <Plus className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page.
// ---------------------------------------------------------------------------

export function Board() {
  const { data, isLoading, isError } = useQuery<BoardData>({
    queryKey: BOARD_KEY,
    queryFn: api.board,
    refetchInterval: 4000, // live: reflect agent-added/moved cards
  });

  const add = useBoardMutation(
    (body: { list: string; title: string }) => api.addBoardCard(body),
    { error: "Couldn't add card" },
  );
  const move = useBoardMutation(
    ({ id, toList }: { id: number; toList: string }) =>
      api.moveBoardCard(id, toList),
    { error: "Couldn't move card" },
  );
  const remove = useBoardMutation((id: number) => api.removeBoardCard(id), {
    error: "Couldn't delete card",
  });
  const addList = useBoardMutation((name: string) => api.addBoardList(name), {
    error: "Couldn't add list",
    success: "List added",
  });

  const lists = data?.lists ?? [];
  const totalCards = lists.reduce((n, l) => n + l.cards.length, 0);
  const [newList, setNewList] = React.useState("");

  return (
    <div>
      <PageHeader
        title="Board"
        description="A workspace board Vox can read and write — plan work and stash notes it can search later."
        actions={
          totalCards > 0 ? (
            <Badge variant="accent" className="font-normal">
              {totalCards} cards
            </Badge>
          ) : null
        }
      />

      {isError && (
        <Card
          glass
          className="mb-6 border-danger/30 px-5 py-4 text-sm text-foreground-secondary"
        >
          Can&apos;t reach the Vox bridge. Is the daemon running on{" "}
          <span className="font-mono">127.0.0.1:8765</span>?
        </Card>
      )}

      {isLoading ? (
        <div className="flex gap-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="w-72 space-y-2">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-20 w-full rounded-xl" />
              <Skeleton className="h-16 w-full rounded-xl" />
            </div>
          ))}
        </div>
      ) : (
        <FadeIn>
          <div className="flex gap-4 overflow-x-auto pb-4">
            {lists.map((list, i) => (
              <Column
                key={list.id}
                name={list.name}
                cards={list.cards}
                canLeft={i > 0}
                canRight={i < lists.length - 1}
                onAdd={(title) => add.mutate({ list: list.name, title })}
                onMove={(card, dir) => {
                  const target = lists[i + dir];
                  if (target) move.mutate({ id: card.id, toList: target.name });
                }}
                onDelete={(card) => remove.mutate(card.id)}
              />
            ))}

            {/* Add a new column */}
            <div className="w-64 shrink-0">
              <div className="mb-2 px-1 text-overline uppercase text-foreground-muted">
                New list
              </div>
              <div className="flex gap-1.5">
                <Input
                  value={newList}
                  onChange={(e) => setNewList(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && newList.trim()) {
                      e.preventDefault();
                      addList.mutate(newList.trim());
                      setNewList("");
                    }
                  }}
                  placeholder="Add a list…"
                  aria-label="Add a list"
                  className="h-8 text-sm"
                />
                <Button
                  variant="ghost"
                  onClick={() => {
                    if (newList.trim()) {
                      addList.mutate(newList.trim());
                      setNewList("");
                    }
                  }}
                  disabled={!newList.trim()}
                  aria-label="Add list"
                  className="h-8 w-8 shrink-0 p-0"
                >
                  <Plus className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </div>
        </FadeIn>
      )}
    </div>
  );
}
