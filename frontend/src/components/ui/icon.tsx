import type { SVGProps } from "react";
const paths = {
  chat: "M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2V11.5a8.5 8.5 0 0 1 17 0ZM7 9h8M7 13h5",
  document: "M14 2H5v20h14V7Zm0 0v5h5M8 12h8M8 16h6",
  graph:
    "M8 5h8M6 7v10M18 7v10M8 19h8M8 7l8 10M4 3h4v4H4ZM16 3h4v4h-4ZM4 17h4v4H4ZM16 17h4v4h-4Z",
  upload: "M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5",
  arrow: "M5 12h14m-6-6 6 6-6 6",
  check: "m5 12 4 4L19 6",
  plus: "M12 5v14M5 12h14",
  minus: "M5 12h14",
  fit: "M9 3H3v6m12-6h6v6M3 15v6h6m6 0h6v-6",
  refresh: "M20 7a8 8 0 1 0 0 10M20 3v5h-5",
} as const;
export function Icon({
  name,
  ...props
}: SVGProps<SVGSVGElement> & { name: keyof typeof paths }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      <path d={paths[name]} />
    </svg>
  );
}
