"use client";

import { useEffect, useRef, useState } from "react";
import { useAssistantDataUI, useThreadRuntime } from "@assistant-ui/react";
import { Button } from "@/components/ui/button";

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

type Decision =
  | { type: "approve" }
  | { type: "reject"; message?: string };

const pressable = "active:scale-[0.98]";

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

  if (decided) {
    return (
      <div className="aui-approval-item-decided text-muted-foreground rounded-md border border-border/60 px-3 py-2 text-sm">
        {decided.type === "approve" ? "✅ Подтверждено" : "❌ Отклонено"}
        {" — "}
        <b>{request.name}</b>
      </div>
    );
  }

  return (
    <div className="aui-approval-item flex flex-col gap-2 rounded-md border border-border/60 p-3">
      {request.description && (
        <p className="text-sm whitespace-pre-line">{request.description}</p>
      )}
      <div className="flex items-center gap-2">
        {allowed.includes("approve") && (
          <Button
            size="sm"
            className={pressable}
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
            className={pressable}
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
