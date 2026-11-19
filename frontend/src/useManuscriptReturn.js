import { useEffect } from "react";

// The dashboard owns selection and can reject navigation when work is unsaved.
export default function useManuscriptReturn(register, handler) {
  useEffect(() => {
    if (!register) return undefined;
    return register(handler);
  });
}
