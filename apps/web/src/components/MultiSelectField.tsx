import { useMemo, useRef, useState } from "react";
import { CaretDown as ChevronDown, Check } from "@phosphor-icons/react";
import { Checkbox } from "@/components/ui/checkbox";
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export type MultiSelectOption = { value: string; label: string };

interface MultiSelectFieldProps {
  label?: string;
  values: string[];
  options: MultiSelectOption[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  ariaLabel?: string;
  searchable?: boolean;
}

function selectedText(values: string[], options: MultiSelectOption[], placeholder: string) {
  if (values.length === 0) return placeholder;
  if (values.length === 1) return options.find((option) => option.value === values[0])?.label ?? values[0];
  return `已选 ${values.length} 项`;
}

export function MultiSelectField({
  label,
  values,
  options,
  onChange,
  placeholder = "请选择",
  ariaLabel,
  searchable = true,
}: MultiSelectFieldProps) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const filteredOptions = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("zh-CN");
    if (!normalized) return options;
    return options.filter((option) => option.label.toLocaleLowerCase("zh-CN").includes(normalized));
  }, [options, query]);
  const selected = useMemo(() => new Set(values), [values]);

  const toggleValue = (value: string) => {
    const next = new Set(values);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    onChange(options.filter((option) => next.has(option.value)).map((option) => option.value));
  };

  const selectVisible = () => {
    const next = new Set(values);
    filteredOptions.forEach((option) => next.add(option.value));
    onChange(options.filter((option) => next.has(option.value)).map((option) => option.value));
  };

  return <div className="multi-select-field">
    {label && <span className="field-label">{label}</span>}
    <Popover open={open} onOpenChange={(next) => { setOpen(next); if (!next) setQuery(""); }}>
      <PopoverTrigger asChild>
        <button ref={triggerRef} type="button" className="multi-select-trigger" aria-label={ariaLabel ?? label} aria-expanded={open} aria-haspopup="listbox">
          <span className={values.length ? "" : "is-placeholder"}>{selectedText(values, options, placeholder)}</span>
          <ChevronDown size={15} aria-hidden="true" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="multi-select-content p-0"
        align="start"
        onOpenAutoFocus={(event) => { event.preventDefault(); const searchInput = (event.currentTarget as HTMLElement).querySelector<HTMLInputElement>("input"); searchInput?.focus(); }}
        onCloseAutoFocus={(event) => { event.preventDefault(); triggerRef.current?.focus(); }}
      >
        <Command shouldFilter={false} className="multi-select-command" role="listbox" aria-label={ariaLabel ?? label} aria-multiselectable="true">
          {searchable && <CommandInput value={query} onValueChange={(value) => setQuery(value)} placeholder="搜索选项" aria-label={`搜索${label ?? "选项"}`} />}
          <div className="multi-select-toolbar"><button type="button" onClick={selectVisible} disabled={!filteredOptions.length}>全选当前结果</button><button type="button" onClick={() => onChange([])} disabled={!values.length}>清空</button></div>
          <CommandList className="multi-select-options">
            {filteredOptions.length ? filteredOptions.map((option) => <CommandItem
              key={option.value}
              value={option.value}
              role="option"
              aria-selected={selected.has(option.value)}
              data-selected={selected.has(option.value) ? "true" : undefined}
              className="multi-select-option"
              onSelect={() => toggleValue(option.value)}
            ><Checkbox checked={selected.has(option.value)} tabIndex={-1} aria-hidden="true" className="pointer-events-none" /><span>{option.label}</span><span className="multi-select-option-check">{selected.has(option.value) && <Check size={15} aria-hidden="true" />}</span></CommandItem>) : <CommandEmpty className="multi-select-empty">没有匹配选项</CommandEmpty>}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  </div>;
}
