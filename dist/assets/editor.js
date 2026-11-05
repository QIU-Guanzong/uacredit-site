const editForm = document.querySelector('#edit-form');
if(editForm) {
  const editor = document.querySelector('#rich-editor');
  const raw = document.querySelector('#raw-content');
  const tools = document.querySelector('.editor-tools');
  editor.hidden=false;raw.hidden=true;tools.hidden=false;
  // The browser owns text selection and native undo. No remote editor or tracking.
  tools.addEventListener('mousedown',event=>event.preventDefault());
  tools.addEventListener('click',event=>{
    const button=event.target.closest('button[data-command]');
    if(!button)return;
    editor.focus();document.execCommand(button.dataset.command,false,button.dataset.value||null);
  });
  editForm.addEventListener('submit',()=>{raw.value=editor.innerHTML;});
  let changed=false;
  editForm.addEventListener('input',()=>{changed=true;});
  editForm.addEventListener('submit',()=>{changed=false;});
  addEventListener('beforeunload',event=>{if(changed){event.preventDefault();event.returnValue='';}});
}
