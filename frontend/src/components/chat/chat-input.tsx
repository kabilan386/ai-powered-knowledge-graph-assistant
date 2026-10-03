import { Icon } from "@/components/ui/icon";
export function ChatInput({
  value,
  onChange,
  onSubmit,
  loading,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  loading: boolean;
}) {
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
      className="chat-form"
    >
      <label htmlFor="question" className="sr-only">
        Your question
      </label>
      <textarea
        id="question"
        placeholder="Ask a question about your documents…"
        rows={2}
        maxLength={4000}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={loading}
        onKeyDown={(event) => {
          if (
            event.key === "Enter" &&
            !event.shiftKey &&
            !event.nativeEvent.isComposing
          ) {
            event.preventDefault();
            if (!loading && value.trim()) onSubmit();
          }
        }}
      />
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted">
          Answers grounded in your knowledge · Enter to send
        </p>
        <button
          className="btn-primary"
          type="submit"
          disabled={loading || !value.trim()}
        >
          {loading ? "Working…" : "Ask question"}
          <Icon name="arrow" width={17} height={17} />
        </button>
      </div>
    </form>
  );
}
