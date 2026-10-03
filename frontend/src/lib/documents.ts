export function maxFileSize(): number {
  const value = Number(process.env.NEXT_PUBLIC_MAX_FILE_SIZE ?? 10485760);
  return Number.isSafeInteger(value) && value > 0 ? value : 10485760;
}
export function validateDocument(
  file: File,
  limit = maxFileSize(),
): string | null {
  if (!/\.(pdf|docx|txt)$/i.test(file.name))
    return "Choose a PDF, DOCX, or TXT document.";
  if (file.size === 0)
    return "The document is empty. Choose a file containing text.";
  if (file.size > limit)
    return `The document exceeds the ${(limit / 1024 / 1024).toFixed(1)} MB upload limit.`;
  return null;
}
export function formatBytes(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
