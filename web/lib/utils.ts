type ClassValue = string | number | boolean | null | undefined | ClassValue[];

export function cn(...inputs: ClassValue[]): string {
  return (inputs as unknown[]).flat(Infinity).filter(Boolean).join(" ");
}
