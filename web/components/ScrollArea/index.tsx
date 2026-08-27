import React, { useEffect, useMemo, useRef } from 'react';
import styles from './ScrollArea.module.scss';
import classNames from 'classnames';
import ScrollAreaContext from './context';
import { useSearchParams } from 'next/navigation';
import { debounce } from 'lodash-es';

const ScrollArea = (props: {
  className?: string;
  style?: React.CSSProperties;
  children: React.ReactNode;
  observe?: boolean;
  id?: string;
  resetScrollTagStr?: string;
  lightScroll?: boolean;
  delayScroll?: boolean;
}) => {
  const {
    className,
    children,
    observe = false,
    id,
    resetScrollTagStr = '',
    lightScroll = false,
    delayScroll,
    ...rest
  } = props;
  const ref = useRef<HTMLDivElement>(null);

  // 在生成内容时，如果鼠标或者手指滑动，禁止滚动区自动滚动到最底部的标志
  const canScrollFlag = useRef(true);
  const maxScrollTopRef = useRef(0);
  const searchParams = useSearchParams();

  useEffect(() => {
    resetScrollTag();
  }, [searchParams]);

  const resetScrollTag = () => {
    canScrollFlag.current = true;
    maxScrollTopRef.current = 0;
  };

  const disableAutoScroll = () => {
    if (!ref.current) return;
    canScrollFlag.current = false;
    maxScrollTopRef.current = Math.max(
      ref.current.scrollTop + ref.current.clientHeight,
      maxScrollTopRef.current,
    );
  };

  const contextValue = useMemo(
    () => ({ resetScrollTag, disableAutoScroll }),
    [resetScrollTag],
  );

  useEffect(() => {
    if (resetScrollTagStr) {
      resetScrollTag();
      computeScroll(ref.current);
    }
  }, [resetScrollTagStr]);

  const computeScroll = debounce((el: any) => {
    if (!el || !canScrollFlag.current) return;
    const height = el.clientHeight;
    const scrollHeight = el.scrollHeight;
    if (scrollHeight > height) {
      el.scrollTo({
        top: scrollHeight - height,
        left: 0,
        behavior: 'smooth',
      });
      maxScrollTopRef.current = scrollHeight;
    }
  }, 5);

  useEffect(() => {
    if (observe && delayScroll) {
      computeScroll(ref.current);
    }
  }, [observe, delayScroll]);

  useEffect(() => {
    const el = ref.current;
    if (el) {
      const isNearBottom = () => {
        const { scrollTop, clientHeight, scrollHeight } = el;
        return scrollHeight - (scrollTop + clientHeight) <= 12;
      };

      const jugeScroll = () => {
        if (!el) return;
        const { scrollTop, clientHeight } = el;
        const isNearBottomNum = 5;
        if (
          maxScrollTopRef.current - (scrollTop + clientHeight) >
          isNearBottomNum
        ) {
          canScrollFlag.current = false;
        } else {
          canScrollFlag.current = true;
        }
        maxScrollTopRef.current = Math.max(
          scrollTop + clientHeight,
          maxScrollTopRef.current
        );
      };

      const scrollHandle = debounce(() => {
        jugeScroll();
      }, 200);

      const fastScrollHandle = debounce(() => {
        jugeScroll();
      }, 10);

      const wheelHandle = (event: WheelEvent) => {
        if (event.deltaY < 0) {
          canScrollFlag.current = false;
          return;
        }
        if (isNearBottom()) {
          canScrollFlag.current = true;
        }
      };

      let flip = false;
      const touchStartHandle = () => {
        flip = true;
      };
      const touchMoveHandle = () => {
        if (flip) {
          jugeScroll();
        }
      };
      const touchEndHandle = () => {
        jugeScroll();
        flip = false;
      };
      el.addEventListener('scrollend', scrollHandle);
      el.addEventListener('mousewheel', fastScrollHandle);
      el.addEventListener('wheel', wheelHandle);
      el.addEventListener('touchstart', touchStartHandle);
      el.addEventListener('touchmove', touchMoveHandle);
      el.addEventListener('touchend', touchEndHandle);

      return () => {
        el.removeEventListener('scrollend', scrollHandle);
        el.removeEventListener('mousewheel', fastScrollHandle);
        el.removeEventListener('wheel', wheelHandle);
        el.removeEventListener('touchstart', touchStartHandle);
        el.removeEventListener('touchmove', touchMoveHandle);
        el.removeEventListener('touchend', touchEndHandle);
      };
    }
  }, []);

  useEffect(() => {
    const el = ref.current;
    const MutationObserver = window.MutationObserver;
    if (el && observe) {
      const ovbserver = new MutationObserver(() => computeScroll(el));
      ovbserver.observe(el, {
        childList: true,
        subtree: true,
        characterData: true,
      });
      return () => {
        ovbserver.disconnect();
      };
    }
  }, [observe]);

  return (
    <div
      ref={ref}
      id={id}
      className={classNames(
        styles.root,
        lightScroll ? styles.light : styles.dark,
        className
      )}
      {...rest}
    >
      <ScrollAreaContext.Provider value={contextValue}>
        {children}
      </ScrollAreaContext.Provider>
    </div>
  );
};

export default ScrollArea;
