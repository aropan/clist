const chat_socket = new WebSocket('wss://' + window.location.host + '/ws/chats/')

chat_socket.onmessage = function(e) {
  const data = JSON.parse(e.data)
  if (data.type == 'new_message') {
    $('.messages').append(
      $('<div class="message"/>')
        .append($('<div class="from"/>').text(data.from.coder))
        .append($('<div class="text"/>').text(data.message))
    )
    ScrollDown()
  }
};

chat_socket.onclose = function(e) {
  console.error('Chat socket closed unexpectedly');
};

function ScrollDown() {
  $('#right').animate({scrollTop: $('#right').prop('scrollHeight')}, 300)
}

$(function() {
  $('#chat-message-input').keyup(function(e) {
    if (e.keyCode === 13) {
      document.querySelector('#chat-message-submit').click();
    }
  })

  $('#chat-message-submit').click(function(e) {
    const messageInputDom = document.querySelector('#chat-message-input');
    const message = messageInputDom.value;
    chat_socket.send(JSON.stringify({
      'action': 'new_message',
      'message': message,
    }));
    messageInputDom.value = '';
  })

  $('#chat-message-input').focus();
  ScrollDown()
})
