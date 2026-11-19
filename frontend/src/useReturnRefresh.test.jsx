import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import useReturnRefresh from './useReturnRefresh';
afterEach(cleanup);
function View({ reload, busy }) { useReturnRefresh(reload, busy); return <p>Manuscripts</p>; }
it('revalidates on return, skips active edits, and detaches on unmount', async () => {
  const reload=vi.fn().mockResolvedValue(undefined);
  const {rerender,unmount}=render(<View reload={reload} busy={false}/>);
  fireEvent.focus(window); await waitFor(()=>expect(reload).toHaveBeenCalledTimes(1));
  rerender(<View reload={reload} busy />); fireEvent.focus(window); await Promise.resolve(); expect(reload).toHaveBeenCalledTimes(1);
  unmount(); fireEvent.focus(window); await Promise.resolve(); expect(reload).toHaveBeenCalledTimes(1);
});
