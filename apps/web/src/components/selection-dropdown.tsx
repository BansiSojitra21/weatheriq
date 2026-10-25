"use client";

import { ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { cn } from "@/lib/utils";

type DropdownOption = {
  value: string;
  label: string;
};

type SelectionDropdownProps = {
  label: string;
  value: string;
  options: DropdownOption[];
  onChange: (value: string) => void;
  className?: string;
  menuClassName?: string;
};

export function SelectionDropdown({ label, value, options, onChange, className, menuClassName }: SelectionDropdownProps) {
  const [open, setOpen] = useState(false);
  const [focusedIndex, setFocusedIndex] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const listId = useId();
  const selectedIndex = Math.max(0, options.findIndex((option) => option.value === value));
  const selectedOption = options[selectedIndex];

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [open]);

  useEffect(() => {
    if (open) optionRefs.current[focusedIndex]?.focus();
  }, [focusedIndex, open]);

  function openAt(index: number) {
    if (!options.length) return;
    setFocusedIndex(Math.max(0, Math.min(index, options.length - 1)));
    setOpen(true);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && open) {
      event.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
      return;
    }
    if (!open) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        openAt(selectedIndex);
      }
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setFocusedIndex((index) => Math.max(0, Math.min(index + (event.key === "ArrowDown" ? 1 : -1), options.length - 1)));
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      setFocusedIndex(event.key === "Home" ? 0 : options.length - 1);
    }
  }

  function selectOption(option: DropdownOption) {
    onChange(option.value);
    setOpen(false);
    triggerRef.current?.focus();
  }

  return (
    <div ref={rootRef} className={cn("relative min-w-0", className)} onKeyDown={handleKeyDown}>
      <button
        ref={triggerRef}
        type="button"
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => (open ? setOpen(false) : openAt(selectedIndex))}
        className="flex h-10 w-full items-center justify-between gap-2 rounded-full bg-muted px-3 text-sm text-foreground outline-none transition-colors hover:bg-muted/80 focus-visible:ring-2 focus-visible:ring-accent"
      >
        <span className="truncate">{selectedOption?.label ?? "Select"}</span>
        <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open ? (
        <div
          id={listId}
          role="listbox"
          aria-label={label}
          className={cn(
            "absolute left-0 top-full z-50 mt-2 max-h-64 w-full min-w-32 overflow-x-hidden overflow-y-auto overscroll-contain rounded-xl border border-border bg-white p-1 shadow-xl",
            menuClassName,
          )}
        >
          {options.map((option, index) => (
            <button
              key={option.value}
              ref={(element) => {
                optionRefs.current[index] = element;
              }}
              type="button"
              role="option"
              aria-selected={option.value === value}
              onClick={() => selectOption(option)}
              className={cn(
                "block w-full truncate rounded-lg px-3 py-2 text-left text-sm text-foreground outline-none hover:bg-muted focus-visible:bg-muted",
                option.value === value && "bg-accent/10 font-medium text-accent",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
