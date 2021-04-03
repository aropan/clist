function chats_height_resize() {
  var left_height = $(window).height() - $('#chats').position().top - 30
  $('.left-chats').css('height', left_height + 'px')
  var right_height = $('.left-sidebar').height() - $('.right-header').outerHeight() - $('.right-chats-textbox').outerHeight() + 1
  $('.right-header-content').css('height', right_height + 'px')
}

$(chats_height_resize)

$(window).resize(function() {
  chats_height_resize()
});
