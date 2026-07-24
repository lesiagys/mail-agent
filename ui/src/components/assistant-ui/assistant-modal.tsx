"use client";

import { BotIcon, ChevronDownIcon } from "lucide-react";

import { type FC, forwardRef, useRef, useState } from "react";
import { AssistantModalPrimitive } from "@assistant-ui/react";

import { Thread } from "@/components/assistant-ui/thread";
import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";

const DEFAULT_WIDTH = 400;
const DEFAULT_HEIGHT = 500;
const MIN_WIDTH = 320;
const MIN_HEIGHT = 360;
const MAX_WIDTH = 900;
const MAX_HEIGHT = 900;

type ResizeDirection = "n" | "w" | "nw";

export const AssistantModal: FC = () => {
  const [size, setSize] = useState({ width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT });
  const sizeRef = useRef(size);
  sizeRef.current = size;

  const startResize = (direction: ResizeDirection) => (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    const target = e.currentTarget;
    target.setPointerCapture(e.pointerId);

    const startX = e.clientX;
    const startY = e.clientY;
    const startWidth = sizeRef.current.width;
    const startHeight = sizeRef.current.height;

    const onMove = (moveEvent: PointerEvent) => {
      const dx = startX - moveEvent.clientX;
      const dy = startY - moveEvent.clientY;

      setSize((prev) => {
        const next = { ...prev };
        if (direction === "w" || direction === "nw") {
          next.width = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth + dx));
        }
        if (direction === "n" || direction === "nw") {
          next.height = Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, startHeight + dy));
        }
        return next;
      });
    };

    const onUp = (upEvent: PointerEvent) => {
      target.releasePointerCapture(upEvent.pointerId);
      target.removeEventListener("pointermove", onMove);
      target.removeEventListener("pointerup", onUp);
    };

    target.addEventListener("pointermove", onMove);
    target.addEventListener("pointerup", onUp);
  };

  return (
    <AssistantModalPrimitive.Root>
      <AssistantModalPrimitive.Anchor className="aui-root aui-modal-anchor fixed end-4 bottom-4 size-11">
        <AssistantModalPrimitive.Trigger asChild>
          <AssistantModalButton />
        </AssistantModalPrimitive.Trigger>
      </AssistantModalPrimitive.Anchor>
      <AssistantModalPrimitive.Content
        sideOffset={16}
        style={{ width: size.width, height: size.height }}
        className="aui-root aui-modal-content bg-popover text-popover-foreground border-border/60 dark:border-muted-foreground/15 data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 data-[state=open]:slide-in-from-bottom-2 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[state=closed]:slide-out-to-bottom-2 [&[data-state=open]_.aui-thread-viewport-footer]:animate-in [&[data-state=open]_.aui-thread-viewport-footer]:fade-in-0 [&[data-state=open]_.aui-thread-viewport-footer]:slide-in-from-bottom-2 [&[data-state=open]_.aui-thread-viewport-footer]:fill-mode-backwards [&>.aui-thread-root_.aui-thread-viewport-footer]:bg-popover z-50 relative max-h-(--radix-popover-content-available-height) max-w-[calc(100vw-2rem)] origin-(--radix-popover-content-transform-origin) overflow-clip overscroll-contain rounded-[2.5rem] border p-0 antialiased shadow-xl ease-[cubic-bezier(0.32,0.72,0,1)] outline-none data-[state=closed]:duration-200 data-[state=open]:duration-300 motion-reduce:animate-none motion-reduce:[&_.aui-thread-viewport-footer]:animate-none [&_[data-slot=aui\_thread-viewport]]:[scrollbar-gutter:stable_both-edges] [&>.aui-thread-root]:bg-inherit [&[data-state=open]_.aui-thread-viewport-footer]:delay-100 [&[data-state=open]_.aui-thread-viewport-footer]:duration-300 [&[data-state=open]_.aui-thread-viewport-footer]:ease-[cubic-bezier(0.32,0.72,0,1)]"
      >
        <Thread />
        <div
          onPointerDown={startResize("n")}
          className="absolute inset-x-4 top-0 h-2 cursor-ns-resize touch-none"
        />
        <div
          onPointerDown={startResize("w")}
          className="absolute inset-y-4 left-0 w-2 cursor-ew-resize touch-none"
        />
        <div
          onPointerDown={startResize("nw")}
          className="absolute top-0 left-0 z-10 size-4 cursor-nwse-resize touch-none"
        />
      </AssistantModalPrimitive.Content>
    </AssistantModalPrimitive.Root>
  );
};

type AssistantModalButtonProps = { "data-state"?: "open" | "closed" };

const AssistantModalButton = forwardRef<
  HTMLButtonElement,
  AssistantModalButtonProps
>(({ "data-state": state, ...rest }, ref) => {
  const tooltip = state === "open" ? "Close Assistant" : "Open Assistant";

  return (
    <TooltipIconButton
      variant="default"
      tooltip={tooltip}
      side="left"
      {...rest}
      className="aui-modal-button size-full rounded-full shadow-lg transition-transform duration-150 ease-out hover:scale-105 active:scale-96 motion-reduce:transition-none"
      ref={ref}
    >
      <BotIcon
        data-state={state}
        className="aui-modal-button-closed-icon absolute size-6 transition-[scale,opacity,filter] duration-200 ease-[cubic-bezier(0.2,0,0,1)] data-[state=closed]:scale-100 data-[state=closed]:opacity-100 data-[state=closed]:blur-[0px] data-[state=open]:scale-25 data-[state=open]:opacity-0 data-[state=open]:blur-[4px] motion-reduce:transition-none"
      />

      <ChevronDownIcon
        data-state={state}
        className="aui-modal-button-open-icon absolute size-6 transition-[scale,opacity,filter] duration-200 ease-[cubic-bezier(0.2,0,0,1)] data-[state=closed]:scale-25 data-[state=closed]:opacity-0 data-[state=closed]:blur-[4px] data-[state=open]:scale-100 data-[state=open]:opacity-100 data-[state=open]:blur-[0px] motion-reduce:transition-none"
      />
      <span className="aui-sr-only sr-only">{tooltip}</span>
    </TooltipIconButton>
  );
});

AssistantModalButton.displayName = "AssistantModalButton";
