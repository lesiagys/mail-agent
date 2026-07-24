"use client";

import { useEffect, useRef, useState } from "react";
import { PencilIcon } from "lucide-react";
import { useAssistantDataUI, useThreadRuntime } from "@assistant-ui/react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Сообщения с этим префиксом — не текст пользователю, а решение по
 * прерванному агенту (approve/reject), отправленное по клику на кнопку.
 * Должен совпадать с DECISION_MARKER в server/main.py.
 */
export const DECISION_MARKER = "__INTERRUPT_DECISION__:";

type ActionRequest = {
  name: string;
  args: Record<string, unknown>;
  description?: string;
};

type ReviewConfig = {
  action_name: string;
  allowed_decisions: string[];
};

type ApprovalData = {
  action_requests: ActionRequest[];
  review_configs: ReviewConfig[];
};

type EditedAction = { name: string; args: Record<string, unknown> };

type Decision =
  | { type: "approve" }
  | { type: "reject"; message?: string }
  | { type: "edit"; edited_action: EditedAction };

const pressable = "active:scale-[0.98]";

const toEmailListText = (to: unknown) =>
  Array.isArray(to) ? to.join(", ") : String(to ?? "");

const formatEditedArgsSummary = (args: Record<string, unknown>) =>
  [
    `Кому: ${toEmailListText(args.to)}`,
    `Тема: ${String(args.subject ?? "")}`,
    "",
    "Текст:",
    String(args.body ?? ""),
  ].join("\n");

/** Инлайн-форма для редактирования полей письма по отдельности (не свободным
 * текстом-комментарием, а прямой правкой того, что предложил агент). */
function FieldEditForm({
  request,
  disabled,
  onSubmit,
  onCancel,
}: {
  request: ActionRequest;
  disabled: boolean;
  onSubmit: (decision: Decision) => void;
  onCancel: () => void;
}) {
  const [initial] = useState(() => ({
    to: toEmailListText(request.args.to),
    subject: String(request.args.subject ?? ""),
    body: String(request.args.body ?? ""),
  }));
  const [to, setTo] = useState(initial.to);
  const [subject, setSubject] = useState(initial.subject);
  const [body, setBody] = useState(initial.body);

  const isDirty =
    to !== initial.to || subject !== initial.subject || body !== initial.body;

  const fieldClass =
    "border-border/60 text-foreground rounded-md border bg-transparent p-2 text-sm outline-none";

  const submit = () => {
    if (!isDirty) return;
    onSubmit({
      type: "edit",
      edited_action: {
        name: request.name,
        args: {
          ...request.args,
          to: to
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          subject,
          body,
        },
      },
    });
  };

  return (
    <div className="flex flex-col gap-2">
      <label className="text-muted-foreground flex flex-col gap-1 text-xs">
        Кому
        <input
          value={to}
          onChange={(e) => setTo(e.target.value)}
          disabled={disabled}
          className={fieldClass}
        />
      </label>
      <label className="text-muted-foreground flex flex-col gap-1 text-xs">
        Тема
        <input
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          disabled={disabled}
          className={fieldClass}
        />
      </label>
      <label className="text-muted-foreground flex flex-col gap-1 text-xs">
        Текст
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          disabled={disabled}
          className={cn(fieldClass, "min-h-24 w-full resize-none")}
        />
      </label>
      <div className="flex flex-col gap-2 @sm:flex-row @sm:items-center">
        <Button
          size="sm"
          className={cn(pressable, "w-full @sm:w-auto")}
          disabled={disabled || !isDirty}
          onClick={submit}
        >
          Отправить правки
        </Button>
        <Button
          size="sm"
          variant="outline"
          className={cn(pressable, "w-full @sm:w-auto")}
          disabled={disabled}
          onClick={onCancel}
        >
          Назад
        </Button>
      </div>
    </div>
  );
}

function ApprovalItem({
  request,
  reviewConfig,
  decided,
  disabled,
  onDecide,
}: {
  request: ActionRequest;
  reviewConfig: ReviewConfig | undefined;
  decided: Decision | null;
  disabled: boolean;
  onDecide: (decision: Decision) => void;
}) {
  const allowed = reviewConfig?.allowed_decisions ?? ["approve", "reject"];
  const [mode, setMode] = useState<"view" | "comment" | "fields">("view");
  const [comment, setComment] = useState("");

  if (decided) {
    const label =
      decided.type === "approve"
        ? "✅ Подтверждено"
        : decided.type === "edit"
          ? "✏️ Правки отправлены"
          : decided.message
            ? "✏️ Отправлены правки"
            : "❌ Отклонено";
    return (
      <div className="aui-approval-item-decided text-muted-foreground rounded-md border border-border/60 px-3 py-2 text-sm">
        {label}
        {" — "}
        <b>{request.name}</b>
        {decided.type === "reject" && decided.message && (
          <p className="text-foreground mt-1 whitespace-pre-line">
            {decided.message}
          </p>
        )}
        {decided.type === "edit" && (
          <p className="text-foreground mt-1 whitespace-pre-line">
            {formatEditedArgsSummary(decided.edited_action.args)}
          </p>
        )}
      </div>
    );
  }

  if (mode === "fields") {
    return (
      <div className="aui-approval-item rounded-md border border-border/60 p-3">
        <FieldEditForm
          request={request}
          disabled={disabled}
          onSubmit={onDecide}
          onCancel={() => setMode("view")}
        />
      </div>
    );
  }

  if (mode === "comment") {
    return (
      <div className="aui-approval-item flex flex-col gap-2 rounded-md border border-border/60 p-3">
        {request.description && (
          <p className="text-sm whitespace-pre-line">{request.description}</p>
        )}
        <textarea
          autoFocus
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="Что поправить?"
          disabled={disabled}
          className="border-border/60 min-h-16 w-full resize-none rounded-md border bg-transparent p-2 text-sm outline-none"
        />
        <div className="flex flex-col gap-2 @sm:flex-row @sm:items-center">
          <Button
            size="sm"
            className={cn(pressable, "w-full @sm:w-auto")}
            disabled={disabled || !comment.trim()}
            onClick={() =>
              onDecide({ type: "reject", message: comment.trim() })
            }
          >
            Отправить правки
          </Button>
          <Button
            size="sm"
            variant="outline"
            className={cn(pressable, "w-full @sm:w-auto")}
            disabled={disabled}
            onClick={() => setMode("view")}
          >
            Назад
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="aui-approval-item relative flex flex-col gap-2 rounded-md border border-border/60 p-3">
      {allowed.includes("edit") && (
        <Button
          size="icon-xs"
          variant="ghost"
          className={cn("absolute top-2 right-2", pressable)}
          disabled={disabled}
          onClick={() => setMode("fields")}
          aria-label="Редактировать поля"
        >
          <PencilIcon />
        </Button>
      )}
      {request.description && (
        <p className="pr-7 text-sm whitespace-pre-line">
          {request.description}
        </p>
      )}
      <div className="flex flex-col gap-2 @sm:flex-row @sm:items-center">
        {allowed.includes("approve") && (
          <Button
            size="sm"
            className={cn(pressable, "w-full @sm:w-auto")}
            disabled={disabled}
            onClick={() => onDecide({ type: "approve" })}
          >
            Подтвердить
          </Button>
        )}
        {allowed.includes("reject") && (
          <Button
            size="sm"
            variant="outline"
            className={cn(pressable, "w-full @sm:w-auto")}
            disabled={disabled}
            onClick={() => setMode("comment")}
          >
            Изменить
          </Button>
        )}
        {allowed.includes("reject") && (
          <Button
            size="sm"
            variant="ghost"
            className={cn(pressable, "w-full @sm:w-auto")}
            disabled={disabled}
            onClick={() => onDecide({ type: "reject" })}
          >
            Отклонить
          </Button>
        )}
      </div>
    </div>
  );
}

function ApprovalCard({ data }: { data: ApprovalData }) {
  const threadRuntime = useThreadRuntime();
  const [decisions, setDecisions] = useState<(Decision | null)[]>(() =>
    data.action_requests.map(() => null),
  );
  const [sent, setSent] = useState(false);
  const sentRef = useRef(false);

  // Отправка — побочный эффект, вынесенный из апдейтера setDecisions:
  // в React StrictMode (dev) функциональные апдейтеры вызываются дважды,
  // и эффект внутри них отправил бы решение на сервер два раза.
  useEffect(() => {
    if (sentRef.current) return;
    if (!decisions.every((d) => d !== null)) return;
    sentRef.current = true;
    setSent(true);
    threadRuntime.append(
      DECISION_MARKER +
        JSON.stringify(decisions.length === 1 ? decisions[0] : decisions),
    );
  }, [decisions, threadRuntime]);

  const decide = (index: number, decision: Decision) => {
    setDecisions((prev) => {
      if (prev[index] !== null) return prev;
      const next = [...prev];
      next[index] = decision;
      return next;
    });
  };

  return (
    <div className="aui-approval-card flex flex-col gap-2 pt-1">
      {data.action_requests.map((request, index) => (
        <ApprovalItem
          key={index}
          request={request}
          reviewConfig={data.review_configs.find(
            (c) => c.action_name === request.name,
          )}
          decided={decisions[index] ?? null}
          disabled={sent}
          onDecide={(decision) => decide(index, decision)}
        />
      ))}
    </div>
  );
}

/** Регистрирует UI подтверждения для data-частей потока с именем "approval". */
export const useInterruptApprovalUI = () => {
  useAssistantDataUI({ name: "approval", render: ApprovalCard });
};
