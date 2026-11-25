import {useState} from 'react';
import {afterEach, expect, it} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import RoleListControls from './RoleListControls';
afterEach(cleanup);
it('keeps clear after sorting and resets search, stage and sort', () => {
  const items=[{manuscript_id:1,title:'Synthetic',status:'revised'}];
  function Fixture(){
    const [search,setSearch]=useState(''), [status,setStatus]=useState(''), [sort,setSort]=useState('recent');
    return <RoleListControls {...{items,search,setSearch,status,setStatus,sort,setSort}} />;
  }
  render(<Fixture/>);
  const search=screen.getByLabelText('Search manuscripts'), stage=screen.getByLabelText('Main stage'), sort=screen.getByLabelText('Sort by');
  const clear=screen.getByRole('button',{name:'Clear filters'});
  expect(sort.compareDocumentPosition(clear) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  fireEvent.change(search,{target:{value:'Synthetic'}});fireEvent.change(stage,{target:{value:'Peer Review'}});fireEvent.change(sort,{target:{value:'title'}});
  fireEvent.click(clear);
  expect(search.value).toBe(''); expect(stage.value).toBe(''); expect(sort.value).toBe('recent');
});
