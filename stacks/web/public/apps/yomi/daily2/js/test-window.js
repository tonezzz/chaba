console.log('test-window.js: Loading...');
window.testFunction = function() {
  console.log('testFunction called');
  return 'success';
};
console.log('test-window.js: window.testFunction =', typeof window.testFunction);
