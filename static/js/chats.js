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
  console.error('Chat socket closed unexpectedly')
  $('#chat-message-input').remove()
  $('#typing-textbox').append($('<button id="chat-message-input" onclick="location.reload()">Disconnected. Refresh the page to reconnect</button>'))
  bootbox.confirm({
    size: 'small',
    message: 'Disconnected. Refresh the page to reconnect?',
    buttons: {
      confirm: {
        label: 'Reload',
        className: 'btn-success',
      },
      cancel: {
        label: 'No',
      },
    },
    callback: function(result) {
      if (result) {
        location.reload()
      }
    },
  })
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
