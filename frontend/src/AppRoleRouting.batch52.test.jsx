import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import App from './App';
vi.mock('./AuthorDashboard',()=>({default:()=> <div>Author workspace marker</div>}));
vi.mock('./EditorDashboard',()=>({default:()=> <div>Editor workspace marker</div>}));
vi.mock('./ReviewerDashboard',()=>({default:()=> <div>Reviewer workspace marker</div>}));
vi.mock('./EICDashboard',()=>({default:()=> <div>EIC workspace marker</div>}));
vi.mock('./FormattingPanel',()=>({default:()=> <div>Formatter workspace marker</div>}));
vi.mock('./NotificationBell',()=>({default:()=>null}));
afterEach(()=>{cleanup();sessionStorage.clear();vi.unstubAllGlobals();});
const response=data=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>data});
for (const [account,choice,expected] of [['author','Author / Submitter','Author'],['reviewer','Peer Reviewer','Reviewer'],['eic','Editor-in-Chief','EIC'],['editor','General / Copy Editor','Editor'],['formatter','General / Copy Editor','Formatter']]) {
  it(`routes an authenticated ${account} through the ${choice} choice`,async()=>{
    vi.stubGlobal('fetch',vi.fn(async url=>String(url).endsWith('/users/auth-options') ? response({captcha:{mode:'off'},google:false}) : String(url).endsWith('/users/login') ? response({access_token:'synthetic'}) : response({user_id:1,name:'Synthetic',role:account})));
    render(<App />);fireEvent.click(await screen.findByRole('button',{name:choice}));
    fireEvent.change(screen.getByLabelText('Email Address'),{target:{value:'synthetic@example.com'}});
    fireEvent.change(screen.getByLabelText('Password'),{target:{value:'Synthetic123!'}});
    fireEvent.click(screen.getByRole('button',{name:'Sign In'}));
    expect(await screen.findByText(`${expected} workspace marker`)).toBeTruthy();
    expect(sessionStorage.getItem('access_token')).toBe('synthetic');
  });
}
it('does not route an author into an EIC workspace when the chooser is changed',async()=>{
  vi.stubGlobal('fetch',vi.fn(async url=>String(url).endsWith('/users/auth-options') ? response({captcha:{mode:'off'},google:false}) : String(url).endsWith('/users/login') ? response({access_token:'synthetic'}) : response({user_id:1,name:'Synthetic',role:'author'})));
  render(<App />);fireEvent.click(await screen.findByRole('button',{name:'Editor-in-Chief'}));
  fireEvent.change(screen.getByLabelText('Email Address'),{target:{value:'synthetic@example.com'}});
  fireEvent.change(screen.getByLabelText('Password'),{target:{value:'Synthetic123!'}});
  fireEvent.click(screen.getByRole('button',{name:'Sign In'}));
  expect(await screen.findByText(/account does not match the selected sign-in role/i)).toBeTruthy();
  expect(screen.queryByText('EIC workspace marker')).toBeNull();
  expect(sessionStorage.getItem('access_token')).toBeNull();
});

it('does not route a formatter account through the Author choice',async()=>{
  vi.stubGlobal('fetch',vi.fn(async url=>String(url).endsWith('/users/auth-options') ? response({captcha:{mode:'off'},google:false}) : String(url).endsWith('/users/login') ? response({access_token:'synthetic'}) : response({user_id:1,name:'Synthetic',role:'formatter'})));
  render(<App />);fireEvent.click(await screen.findByRole('button',{name:'Author / Submitter'}));
  fireEvent.change(screen.getByLabelText('Email Address'),{target:{value:'synthetic@example.com'}});
  fireEvent.change(screen.getByLabelText('Password'),{target:{value:'Synthetic123!'}});
  fireEvent.click(screen.getByRole('button',{name:'Sign In'}));
  expect(await screen.findByText(/account does not match the selected sign-in role/i)).toBeTruthy();
  expect(screen.queryByText('Author workspace marker')).toBeNull();
  expect(sessionStorage.getItem('access_token')).toBeNull();
});
