import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));

export const eur = (n: number) => "€" + Math.round(n).toLocaleString("en-IE");
