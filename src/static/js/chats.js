const chat_socket = new WebSocket('wss://' + window.location.host + '/ws/chats/')

function AddMessage(data, method='append') {
  time_ago = $('<time class="timeago" data-placement="right"/>').text($.timeago(data.when))
  time_ago.attr('title', (new Date(data.when)).toLocaleString())
  time_ago.attr('datetime', data.when)
  time_ago.timeago()
  toggle_tooltip_object(time_ago)

  $('.messages')[method](
    $('<div class="message"/>')
      .append($('<div class="title"/>')
        .append($('<div class="from"/>').text(data.from.coder))
        .append($('<div class="time"/>').append(time_ago))
      )
      .append($('<div class="text"/>').text(data.message))
  )
}

chat_socket.onmessage = function(e) {
  const data = JSON.parse(e.data)
  if (data.type == 'new_message') {
    AddMessage(data)
    ScrollDown()
  } else if (data.type == 'history') {
    $('.message.loading').remove()
    history_id = $('#chat-history-id')
    if (data.history.length == 0) {
      history_id.remove()
    } else {
      history_id_val = history_id.val()
      top_message = $('.messages').children().first()
      for (idx in data.history) {
        record = data.history[idx]
        AddMessage(record.data, 'prepend')
        history_id.val(record.id)
      }

      if (!history_id_val) {
        ScrollDown()
      } else if (top_message.length) {
        var previous_height = 0;
        top_message.prevAll().each(function() {
          previous_height += $(this).outerHeight();
        });
        $('#right').scrollTop(previous_height);
      }
    }
  }
};

chat_socket.onclose = function(e) {
  console.error('Socket closed unexpectedly')
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

chat_socket.onopen = function (e) {
  LoadHistroy()
}

function ScrollDown() {
  $('#right').animate({scrollTop: $('#right').prop('scrollHeight')}, 300)
}

function LoadHistroy() {
  history_id = $('#chat-history-id')
  if (history_id.length) {
    $('.messages').prepend($('<div class="message loading"><i class="fa-2x fas fa-spinner fa-spin"></i></div>'))
    chat_socket.send(JSON.stringify({
      'action': 'get_logs',
      'chat': $('#chat-name').val(),
      'id': history_id.val(),
    }));
  }
}

function OnScroll() {
  if ($('#right').scrollTop() == 0 && $('.message.loading').length == 0) {
    LoadHistroy()
  }
}


$(function() {
  $('#chat-message-input').keyup(function(e) {
    if (e.keyCode === 13) {
      document.querySelector('#chat-message-submit').click()
    }
  })

  $('#chat-message-submit').click(function(e) {
    message_input = $('#chat-message-input')
    text = message_input.val()
    if (text) {
      chat_socket.send(JSON.stringify({
        'action': 'new_message',
        'message': text,
        'chat': $('#chat-name').val(),
      }))
    }
    message_input.val('')
  })

  $('#right').scroll(OnScroll)

  $('#chat-message-input').focus()
})
