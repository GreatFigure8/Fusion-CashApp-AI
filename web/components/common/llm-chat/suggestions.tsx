import { Button } from "@/components/ui/button";

type SuggestionsProps = {
  suggestions: readonly string[];
  disabled: boolean;
  onPick: (text: string) => void;
};

export function Suggestions({ suggestions, disabled, onPick }: SuggestionsProps) {
  return (
    <div className="flex flex-col items-start gap-2" data-slot="chat-suggestions">
      <p className="text-xs text-muted-foreground">Try asking</p>
      <div className="flex flex-wrap gap-2">
        {suggestions.map((text) => (
          <Button
            key={text}
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled}
            onClick={() => onPick(text)}
          >
            {text}
          </Button>
        ))}
      </div>
    </div>
  );
}
