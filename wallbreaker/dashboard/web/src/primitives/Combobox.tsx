import { useId, useRef, useState, type ReactNode } from "react";

export interface ComboboxOption {
  value: string;
  label?: ReactNode;
}

/**
 * Combobox (accessibility) — an input with role="combobox", aria-expanded and
 * aria-controls pointing at a role="listbox". Each option carries a stable id;
 * aria-activedescendant tracks the arrow-key-highlighted option so screen readers
 * announce the current choice without moving DOM focus off the input.
 */
export function Combobox({
  value,
  options,
  onChange,
  onSelect,
  placeholder,
  ariaLabel = "Combobox",
  disabled = false,
}: {
  value: string;
  options: ComboboxOption[];
  onChange: (value: string) => void;
  onSelect: (value: string) => void;
  placeholder?: string;
  ariaLabel?: string;
  disabled?: boolean;
}) {
  const baseId = useId();
  const listId = `${baseId}-listbox`;
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);

  const optionId = (index: number) => `${baseId}-opt-${index}`;
  const close = () => { setOpen(false); setActive(-1); };
  const pick = (option: ComboboxOption) => { onSelect(option.value); close(); };

  return (
    <div ref={rootRef} className="combobox">
      <input
        type="text"
        role="combobox"
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && active >= 0 ? optionId(active) : undefined}
        autoComplete="off"
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        onFocus={() => setOpen(true)}
        onChange={(event) => { onChange(event.target.value); setOpen(true); setActive(-1); }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true);
            setActive((index) => Math.min(index + 1, options.length - 1));
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setActive((index) => Math.max(index - 1, 0));
          } else if (event.key === "Enter") {
            if (active >= 0 && options[active]) { event.preventDefault(); pick(options[active]); }
          } else if (event.key === "Escape") {
            close();
          }
        }}
      />
      {open && (
        <ul className="combobox-listbox" id={listId} role="listbox" aria-label={ariaLabel}>
          {options.map((option, index) => (
            <li
              key={option.value}
              id={optionId(index)}
              role="option"
              aria-selected={option.value === value}
              className={index === active ? "active" : ""}
              onMouseDown={(event) => event.preventDefault()}
              onMouseEnter={() => setActive(index)}
              onClick={() => pick(option)}
            >
              {option.label ?? option.value}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
