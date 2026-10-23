"use client";

import { useRef, useState, useSyncExternalStore } from "react";
import { MicIcon, SquareIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type RecognitionEvent = {
  resultIndex: number;
  results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }>;
};

type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: RecognitionEvent) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start: () => void;
  stop: () => void;
};

type RecognitionCtor = new () => Recognition;

function recognitionCtor(): RecognitionCtor | null {
  const w = window as unknown as {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const noSubscribe = () => () => {};

type MicButtonProps = {
  /** Called with each finished phrase; the composer appends it to the message. */
  onTranscript: (text: string) => void;
  disabled?: boolean;
};

/** Dictation through the browser's speech recognition. Renders nothing where it is unsupported. */
export function MicButton({ onTranscript, disabled }: MicButtonProps) {
  const supported = useSyncExternalStore(noSubscribe, () => recognitionCtor() !== null, () => false);
  const [listening, setListening] = useState(false);
  const active = useRef<Recognition | null>(null);

  if (!supported) return null;

  const toggle = () => {
    if (active.current) {
      active.current.stop();
      return;
    }
    const Ctor = recognitionCtor();
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = navigator.language || "en-US";
    rec.continuous = true;
    rec.interimResults = false;
    rec.onresult = (event) => {
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const phrase = result?.[0]?.transcript.trim();
        if (result?.isFinal && phrase) onTranscript(phrase);
      }
    };
    const finish = () => {
      active.current = null;
      setListening(false);
    };
    rec.onend = finish;
    rec.onerror = finish;
    active.current = rec;
    setListening(true);
    rec.start();
  };

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      aria-label={listening ? "Stop dictation" : "Dictate"}
      aria-pressed={listening}
      disabled={disabled}
      onClick={toggle}
      className={cn("size-9 rounded-lg text-muted-foreground", listening && "text-err")}
    >
      {listening ? <SquareIcon className="size-3.5 fill-current" /> : <MicIcon />}
    </Button>
  );
}
