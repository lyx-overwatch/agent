import { Dialog, Transition } from '@headlessui/react';
import { Fragment } from 'react';
import { XMarkIcon } from '@heroicons/react/24/solid';
import classNames from 'classnames';

type IModal = {
  className?: string;
  wrapperClassName?: string;
  containClassName?: string;
  maskClassName?: string;
  isShow: boolean;
  onClose: () => void;
  title?: React.ReactNode;
  children: React.ReactNode;
  closable?: boolean;
  closeClass?: string;
  maskClick?: boolean;
};

// headlessui Dialog 内部已用 Portal 渲染到 body 末尾，无需手动 createPortal
export default function Modal({
  className = '',
  wrapperClassName = '',
  containClassName = '',
  maskClassName = '',
  isShow,
  onClose,
  title,
  children,
  closable = false,
  closeClass,
  maskClick = true,
}: IModal) {
  return (
    <Transition appear show={isShow} as={Fragment}>
      <Dialog
        className={classNames('relative z-[999]', wrapperClassName)}
        onClose={() => {
          if (maskClick) onClose();
        }}
      >
        <Transition.Child
          as={Fragment}
          enter='ease-out duration-300'
          enterFrom='opacity-0'
          enterTo='opacity-100'
          leave='ease-in duration-200'
          leaveFrom='opacity-100'
          leaveTo='opacity-0'
        >
          <div
            className={classNames(
              'fixed top-0 left-0 right-0 bottom-0 bg-black bg-opacity-25',
              maskClassName
            )}
          >
            <button className='h-0 w-0 overflow-hidden' />
          </div>
        </Transition.Child>

        <div className='fixed top-0 left-0 right-0 bottom-0 overflow-y-auto'>
          <div
            className={classNames(
              'flex h-full items-center justify-center p-4 text-center mobile:relative',
              containClassName
            )}
          >
            <Transition.Child
              as={Fragment}
              enter='ease-out duration-300'
              enterFrom='opacity-0 scale-95'
              enterTo='opacity-100 scale-100'
              leave='ease-in duration-200'
              leaveFrom='opacity-100 scale-100'
              leaveTo='opacity-0 scale-95'
            >
              <Dialog.Panel
                className={classNames(
                  'max-w-full relative min-w-[28rem] mobile:min-w-0 mobile:w-full overflow-hidden rounded-2xl bg-white p-6 text-left align-middle shadow-xl transition-all',
                  className
                )}
              >
                {title && (
                  <Dialog.Title
                    as='h3'
                    className='text-lg leading-6 text-[#171c1e] font-semibold mobile:text-center mobile:max-w-[calc(100%_-_96px)] mobile:mx-auto mobile:whitespace-nowrap mobile:text-ellipsis mobile:overflow-hidden'
                  >
                    {title}
                  </Dialog.Title>
                )}
                {closable && (
                  <div
                    className={classNames(
                      'absolute top-6 right-6 mobile:top-2  w-6 z-10 h-6 rounded-2xl flex items-center justify-center hover:cursor-pointer hover:bg-gray-100',
                      closeClass
                    )}
                  >
                    <XMarkIcon
                      className='w-6 h-6 text-[#171c1e]'
                      onClick={onClose}
                    />
                  </div>
                )}
                <div className={title ? 'h-[calc(100%_-_24px)]' : 'h-full'}>
                  {children}
                </div>
              </Dialog.Panel>
            </Transition.Child>
          </div>
        </div>
      </Dialog>
    </Transition>
  );
}
