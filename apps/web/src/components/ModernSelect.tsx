import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export type SelectOption = { value: string; label: string };

/**
 * One keyboard-accessible select used throughout the app. Keeping the Radix
 * primitive in a small component makes the visual contract consistent across
 * filters, stages, preferences and event forms.
 */
export function ModernSelect({ label, value, onChange, options, placeholder = "请选择", compact = false, ariaLabel, name, autoComplete = "off" }: { label?: string; value: string; onChange: (value: string) => void; options: SelectOption[]; placeholder?: string; compact?: boolean; ariaLabel?: string; name?: string; autoComplete?: string }) {
  const selectValue = value || "__all__";
  return <div className={`modern-select ${compact ? "is-compact" : ""}`}>
    {label && <span className="field-label">{label}</span>}
    <Select name={name} autoComplete={autoComplete} value={selectValue} onValueChange={(next) => onChange(next === "__all__" ? "" : next)}>
      <SelectTrigger className="select-trigger" aria-label={ariaLabel || label}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent className="select-content" position="popper" sideOffset={6}>
        {options.map((option) => <SelectItem className="select-item" key={option.value} value={option.value}>{option.label}</SelectItem>)}
      </SelectContent>
    </Select>
  </div>;
}
