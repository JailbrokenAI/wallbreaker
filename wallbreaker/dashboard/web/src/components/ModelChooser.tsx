import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { ModelCatalog } from "../api";
import { cachedModelCatalog, loadModelCatalog, rememberModel, subscribeModelCatalog } from "../dataCache";

export function ModelChooser({
  value,
  profile,
  onChange,
  onCommit,
  placeholder = "Paste or choose a model id",
  disabled = false,
  compact = false,
  ariaLabel = "Model",
}: {
  value: string;
  profile: string;
  onChange: (value: string) => void;
  onCommit?: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  compact?: boolean;
  ariaLabel?: string;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  // A11Y-2: stable ids wire the combobox input to its listbox (aria-controls) and
  // the arrow-highlighted option (aria-activedescendant), matching the Combobox
  // primitive's contract while keeping this component's async catalog behaviour.
  const baseId = useId();
  const listId = `${baseId}-listbox`;
  const optionId = (index: number) => `${baseId}-opt-${index}`;
  const [open, setOpen] = useState(false);
  const [catalog, setCatalog] = useState<ModelCatalog | null>(() => cachedModelCatalog(profile));
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(-1);
  const [query, setQuery] = useState("");

  // REL-5: `isCurrent` lets the effect discard a catalog response that arrives
  // after the profile changed, so a superseded load never overwrites newer state.
  const load = useCallback(async (isCurrent: () => boolean = () => true) => {
    if (!profile) {
      if (isCurrent()) setCatalog(null);
      return;
    }
    setLoading(true);
    try {
      const result = await loadModelCatalog(profile);
      if (isCurrent()) setCatalog(result);
    } catch (error) {
      if (isCurrent()) setCatalog({
        profile,
        protocol: "",
        models: [],
        fetched: false,
        error: (error as Error).message,
      });
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [profile]);

  useEffect(() => {
    let active = true;
    setCatalog(cachedModelCatalog(profile));
    setActive(-1);
    if (open) void load(() => active);
    return () => { active = false; };
  }, [profile, open, load]);

  useEffect(() => subscribeModelCatalog(profile, setCatalog), [profile]);

  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const choices = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    const models = catalog?.models || [];
    if (!normalizedQuery) return models.slice(0, 100);
    return models
      .filter((model) => model.toLocaleLowerCase().includes(normalizedQuery))
      .sort((left, right) => {
        const leftStarts = left.toLocaleLowerCase().startsWith(normalizedQuery);
        const rightStarts = right.toLocaleLowerCase().startsWith(normalizedQuery);
        return leftStarts === rightStarts ? left.localeCompare(right) : leftStarts ? -1 : 1;
      })
      .slice(0, 100);
  }, [catalog, query]);

  const openMenu = (resetQuery = true) => {
    if (disabled) return;
    if (resetQuery) setQuery("");
    setOpen(true);
  };
  const choose = (model: string) => {
    onChange(model);
    onCommit?.(model);
    setOpen(false);
    setActive(-1);
    setQuery("");
  };
  const commitCustom = () => {
    const model = value.trim();
    if (model) {
      void rememberModel(profile, model).catch(() => undefined);
      onCommit?.(model);
    }
    setOpen(false);
  };

  return (
    <div ref={rootRef} className={`model-chooser ${compact ? "compact" : ""}`}>
      <div className="model-chooser-control">
        <input
          type="text"
          role="combobox"
          aria-label={ariaLabel}
          aria-expanded={open}
          aria-controls={listId}
          aria-activedescendant={open && active >= 0 ? optionId(active) : undefined}
          aria-autocomplete="list"
          autoComplete="off"
          value={value}
          placeholder={placeholder}
          disabled={disabled}
          onFocus={(event) => {
            event.currentTarget.select();
            openMenu();
          }}
          onClick={() => openMenu()}
          onChange={(event) => {
            onChange(event.target.value);
            setQuery(event.target.value);
            setOpen(true);
            setActive(-1);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              openMenu(false);
              setActive((index) => Math.min(index + 1, choices.length - 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setActive((index) => Math.max(index - 1, 0));
            } else if (event.key === "Enter") {
              event.preventDefault();
              if (active >= 0 && choices[active]) choose(choices[active]);
              else commitCustom();
            } else if (event.key === "Escape") {
              setOpen(false);
            }
          }}
        />
        <button
          type="button"
          className="model-chooser-toggle"
          disabled={disabled}
          tabIndex={-1}
          title="Show available models"
          aria-label="Show available models"
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => open ? setOpen(false) : openMenu()}
        >
          ▾
        </button>
      </div>
      {open && (
        <div className="model-chooser-menu" role="listbox" id={listId} aria-label={ariaLabel}>
          <div className="model-chooser-source">
            <span>{profile || "No profile selected"}</span>
            {catalog?.fetched && <span>{catalog.models.length} models</span>}
          </div>
          {loading && <div className="model-chooser-state">Loading models...</div>}
          {!loading && choices.map((model, index) => (
            <button
              type="button"
              role="option"
              id={optionId(index)}
              aria-selected={model === value}
              key={model}
              className={index === active ? "active" : ""}
              onMouseDown={(event) => event.preventDefault()}
              onMouseEnter={() => setActive(index)}
              onClick={() => choose(model)}
            >
              {model}
            </button>
          ))}
          {!loading && !choices.length && value.trim() && (
            <button type="button" className="custom-model" onClick={commitCustom}>
              Use custom model "{value.trim()}"
            </button>
          )}
          {!loading && !choices.length && !value.trim() && (
            <div className="model-chooser-state">Type or paste a custom model id.</div>
          )}
          {catalog?.error && <div className="model-chooser-warning">{catalog.error}</div>}
        </div>
      )}
    </div>
  );
}
