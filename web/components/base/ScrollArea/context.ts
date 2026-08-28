import { createContext } from 'use-context-selector';

type ContextValue = {
  resetScrollTag: () => void;
  disableAutoScroll?: () => void;
};

const ScrollAreaContext = createContext<ContextValue>({
  resetScrollTag: () => undefined,
  disableAutoScroll: () => undefined,
});

export default ScrollAreaContext;
