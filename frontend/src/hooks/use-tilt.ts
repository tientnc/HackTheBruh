import { useCallback, useRef } from "react";

/**
 * Returns ref + event handlers that apply a subtle 3-D tilt transform
 * on mouse move and reset on mouse leave.
 *
 * Usage:
 *   const tilt = useTilt();
 *   <div ref={tilt.ref} onMouseMove={tilt.onMouseMove} onMouseLeave={tilt.onMouseLeave} />
 *
 * Respects prefers-reduced-motion: when the media query matches, no
 * transform is applied (the CSS layer also disables transitions, but
 * this ensures the JS side is also a no-op).
 */
export function useTilt(maxDeg = 5, perspective = 800) {
  const ref = useRef<HTMLElement | null>(null);
  const reduced =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const onMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (reduced || !ref.current) return;
      const rect = ref.current.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width - 0.5; // -0.5 … +0.5
      const y = (e.clientY - rect.top) / rect.height - 0.5;
      const ry = x * maxDeg * 2;
      const rx = -y * maxDeg * 2;
      ref.current.style.transform = `perspective(${perspective}px) rotateX(${rx}deg) rotateY(${ry}deg)`;
    },
    [reduced, maxDeg, perspective],
  );

  const onMouseLeave = useCallback(() => {
    if (reduced || !ref.current) return;
    ref.current.style.transform = "";
  }, [reduced]);

  return { ref, onMouseMove, onMouseLeave } as const;
}

