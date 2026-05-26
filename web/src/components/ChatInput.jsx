function ChatInput({
  value,
  onChange,
  onSend,
  onCancel,
  isStreaming,
  disabled,
}) {
  const handleKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      onSend();
    }
  };

  return (
    <div className="border-t border-border/60 px-5 py-4">
      <textarea
        className="w-full resize-none rounded-xl border border-border/60 bg-surface/70 px-4 py-3 text-sm text-text placeholder:text-muted focus:border-accent/60 focus:outline-none"
        rows={3}
        placeholder="Ask the assistant or drop a system message..."
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
      />
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <span className="text-xs text-muted">Shift + Enter for newline</span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="rounded-full border border-border/70 px-4 py-2 text-xs font-semibold uppercase tracking-[0.2em] text-muted transition hover:text-text disabled:opacity-50"
            onClick={onCancel}
            disabled={!isStreaming}
          >
            Cancel Generation
          </button>
          <button
            type="button"
            className="rounded-full bg-accent px-4 py-2 text-xs font-semibold uppercase tracking-[0.2em] text-slate-900 shadow-glow transition hover:translate-y-[-1px] disabled:opacity-60"
            onClick={onSend}
            disabled={disabled || !value.trim()}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

export default ChatInput;
