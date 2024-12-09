/* global jQuery */
/**
 * AddCalEvent.js

 * @author Mike Sendlakowski, msendlakowski@ebay.com
 *
 * Adds functionality to a button element to all users to add an event
 * to various calendar apps
 *
 * Usage:
 * All parameters are optional. However, if you want this to work for Outlook and iCal you must
 * provide the url that will generate the ics file response
 *
 * $(SELECTOR).addcalevent({
 *    'onclick': true,
 *    'apps': [1,2,4],
 *    'ics': '',
 *    'data': {}
 * });
 *
 * onclick: Open the dropdown on click rather than mouseover (default: false)
 * data: Event data (see below for format). This can also be set individually as a json string directly on each HTML element.
 * linkText: Array containing localized or customized text for the calendar links (order is critical)
 * ics: Url that will generate the server-side ics response based on the event details. Not optional if Outlook or iCal is needed.
 * apps: Array containing the applications available to the user. (default: [] - which is all apps)
 *            0 = Outlook
 *            1 = Google
 *            2 = Yahoo
 *            3 = Hotmail
 *            4 = iCal
 *
 * Format of event data object:
 *
 * title: '',
 * desc: '',
 * location: '',
 * url: '',         // only available in Yahoo calendars
 * organizer: {     // only available in Outlook
 *    name: '',
 *    email: ''
 * },
 * time: {
 *    start: '',    // 'month day, year 14:30:00'
 *    end: '',      // 'month day, year 14:30:00'
 *    zone: '',     // '+tt:tt' - plus or minus from UTC time zone (example: Pacific Daylight Time is '-07:00')
 *    allday: false
 * }
 *
 */

(function(window, $, undefined) {
    'use strict';

    // CONSTANTS
    var EVENT_SHOW = 'AddCalEvent:show',
    EVENT_ADDED = 'AddCalEvent:add',
    EVENT_INVALID = 'AddCalEvent:invalid',
    DEFAULT_EVENT = {
        title: '',
        desc: '',
        location: '',
        url: '',
        organizer: {name: '', email: ''},
        time: {
            start: '',
            end: '',
            zone: '00:00',
            allday: false
        }
    };

    $.addcalevent = function addcalevent(options, element) {
        this.el = $(element);
    // Flag the object in the event of a failed creation
    if (!this._create(options)) {
      this.failed = true;
    }
  };

  $.addcalevent.defaults = {
        onclick: false,
        apps: [],
        ics: '',
        preVal: true,
        disabledClass: "dis",
        linkText: [
            'Outlook',
            'Google',
            'Yahoo',
            'Outlook',
            'iCal'
        ]
    };

    $.addcalevent.prototype = {

    /*
    ----------------------------
    Private methods
    ----------------------------
    */

    _create: function(options){
      this.options = $.extend(true, {}, $.addcalevent.defaults, options);
            if(this.options.preVal){
                this._disable(!this._sanitizeData());
            }
            this._attach();
            return true;
        },

        // add the basic hook to the button
        _attach: function() {
            var self = this;

            // handle clicking on a calendar link
            this.el.on('click', '.ace_opt', function(event){self._click(this, event);});

            // handle opening and closing the dropdown - always available for accessiblity
            this.el.on('click', function(event){self._clickShow(event);});
            $(document).on('click', function(){self._hide();});

            // handle opening and closing the dropdown on mouseover
            if(!this.options.onclick) {
                this.el.on('mouseover', function(){self._show();});
                this.el.on('mouseout', function(){self._hide();});
            }
        },

        // onclick handler for button (not calendar links)
        _clickShow: function(event) {
            if (this.options.apps.length == 1) {
              this._addEvent(this.options.apps[0])
            }
            else if(this.open) {
                this._hide();
            } else {
                this._show();
                this.open = true;
            }
            event.stopPropagation();
        },

        // show the dropdown
        _show: function() {
            var self = this;
            if(!this.dd) {
                this._createDropdown();
            }
            this.dd.stop();
            this.dd.clearQueue();
            if(this.opening) {  // its already started animating, so finish it immediately
                this.dd.show();
                self.dd.css(self.ddCss);
            } else {
                this.dd.show('fast');
                this.opening = true;
                this._eventPublisher(EVENT_SHOW);
            }
        },

        // hide the dropdown
        _hide: function() {
            var self = this;
            if(!this.dd) { // if it doesn't have a dropdown then no need to hide it. duh!
                return;
            }
            this.open = false;
            this.dd.stop();
            this.dd.clearQueue();
            this.dd.hide('fast', function(){
                self.opening = false;
                self.dd.css(self.ddCss); // reset the height and opacity, because the jquery animation was losing it when we call stop
            });
        },

        // create the dropdown
        _createDropdown: function(showOpts) {
            var isValid = this._sanitizeData();
            this._disable(!isValid);
            this.dd = $(this._createHtml(isValid));
            this.el.append(this.dd);
            this.ddCss = {
                height: this.dd.css("height"),
                opacity: 1
            }
        },

        _disable:function(disable){
            this.el.toggleClass(this.options.disabledClass, disable);
        },

        // create the html for the dropdown
        _createHtml: function(isValid) {
            var styleString = this._getStyle(),
            optionLinks = '';
            for(var i=0,j=this.options.linkText.length;i<j;i++) {
                if(this._isLinkNeeded(i)) {
                    optionLinks += '<a class="ace_opt" data-ace-id="'+ i +'" href="javascript:;">' + this.options.linkText[i] + '</a>';
                }
            }
            return '<div class="ace_dd" style="' + styleString + '">' + optionLinks + '</div>';
        },

        // test to see if we need to display this link
        _isLinkNeeded: function(linkId) {
            var isOK = false,
            appLength = this.options.apps.length;
            if(appLength === 0) {
                isOK = this._runIcsTest(linkId);
            } else {
                for(var y=0,z=this.options.apps.length;y<z;y++) {
                    if(this.options.apps[y] === linkId) {
                        isOK = this._runIcsTest(linkId);
                        break;
                    }
                }
            }
            return isOK;
        },

        // only show the outlook and ical links if the ics url is available
        _runIcsTest: function(linkId) {
            var isOK = false;
            if(linkId === 0 || linkId === 4) {
                if(this.options.ics !== '') {
                    isOK = true;
                }
            } else {
                isOK = true;
            }
            return isOK;
        },

        // get the absolute position and min-width based on the parent button
        // could cause issues if the button moves around the page dynamically when it resizes
        _getStyle: function() {
            var pos = this.el.offset(),
            left = pos.left + parseFloat(this.el.css('marginLeft')),
            top = pos.top + this.el.outerHeight() + parseFloat(this.el.css('marginTop')) - 1,
            minwidth = this.el.outerWidth() - parseFloat(this.el.css('borderLeftWidth'));
            return 'min-width:' + minwidth + 'px;top:' + top + 'px;left:' + left + 'px';
        },

        // make sure all event data is available and valid
        _sanitizeData: function() {
            var testData = this._getDataFromEl(),
            isValid = true,
            zoneRegex = /^[\+\-]?[0-9]{2}:[0-9]{2}/;

            if(!testData) {
                testData = this.options.data;
            }
            this.options.data = $.extend(true, {}, DEFAULT_EVENT, testData);
            this.options.data.timeObj = {};

            // is the start date valid?
            this.options.data.timeObj.start = new Date(this.options.data.time.start);
            if(isNaN(this.options.data.timeObj.start.getTime())) {
                isValid = false;
                this._eventPublisher(EVENT_INVALID, {invalidStartDate: this.options.data.time.start});
            }

            // is the end date valid?
            this.options.data.timeObj.end = new Date(this.options.data.time.end);
            if(isNaN(this.options.data.timeObj.end.getTime())) {
                isValid = false;
                this._eventPublisher(EVENT_INVALID, {invalidEndDate: this.options.data.time.end});
            }

            // is the time zone valid?
            this._lookupTimeZone();
            if(this.options.data.time.zone.length < 6) {
                this.options.data.time.zone = '+' + this.options.data.time.zone;
            }

            if(!zoneRegex.test(this.options.data.time.zone)) {
                isValid = false;
                this._eventPublisher(EVENT_INVALID, {invalidTimeZone: this.options.data.time.zone});
                this.options.data.time.zone = '+00:00';
            }

            return isValid;
        },

        // translates a time zone abbreviation to an offset, as long as
        // AddCalEventZones.js is loaded. But ideally the zone offset is identified on the server.
        _lookupTimeZone: function(){
            if(AddCalEventZones && AddCalEventZones[this.options.data.time.zone]) {
                this.options.data.time.zone = AddCalEventZones[this.options.data.time.zone];
            }
        },

        // get the data from the html element rather than the plugin config
        _getDataFromEl: function(){
            var data = this.el.data('ace');
            if(typeof data === 'string') {
                this._eventPublisher(EVENT_INVALID, {invalidDataString: data});
                data = null;
            }
            return data;
        },

        // update the event options
        _update: function(options){
            this.options = $.extend(true, {}, $.addcalevent.defaults, options);
            if(this.options.preVal){
                this._disable(!this._sanitizeData());
            }
            return true;
        },

        // an event link was clicked
        _click: function(item, event) {
            var id = $(item).data('ace-id');
            this._addEvent(id);
            event.stopPropagation();
            this._hide();
        },

        // create an 'add to calendar' url and open it in a new window
        // most of the details were taken from this article:
        // http://richmarr.wordpress.com/2008/01/07/adding-events-to-users-calendars-part-2-web-calendars/
        _addEvent: function(calendarLinkType){
            var url,
                sameWindow;
            switch(calendarLinkType) {
            case 0:     //Outlook
            case 4:     // iCal
                url = this._getUrl_ics();
                sameWindow = true;
                break;
            case 1:     // Google
                url = this._getUrl_google();
                break;
            case 2:     // Yahoo
                url = this._getUrl_yahoo();
                break;
            case 3:     // Hotmail
                url = this._getUrl_hotmail();
                break;
            }
            if(url) {
                if(sameWindow) {
                    location.href = url;
                } else {
                    window.open(url, 'calendar');
                }
            }
            this._eventPublisher(EVENT_ADDED, {calendarLinkType: calendarLinkType, url: url});
        },

        _getUTCTime: function(dateObj) {
            var newDateObj = this._adjustToUTC(dateObj, this.options.data.time.zone);
            return this._getDatePart(newDateObj.getFullYear(),4) + this._getDatePart(newDateObj.getMonth()+1,2) + this._getDatePart(newDateObj.getDate(),2) + 'T' + this._getDatePart(newDateObj.getHours(),2) + this._getDatePart(newDateObj.getMinutes(),2) + this._getDatePart(newDateObj.getSeconds(),2) + 'Z';
        },

        // return a new date object based on dateObj and the zone
        _adjustToUTC: function(dateObj, zone){
            var dateOut = new Date(dateObj),
            hours, mins;

            if(isNaN(dateOut.getTime())) {
                return new Date();
            }

            // adjust to UTC
            hours = zone.substring(1,3);
            mins = zone.substring(4,6);
            if(zone.substring(0,1) === '-') {
                dateOut.setHours(dateOut.getHours() + (hours-0));
                dateOut.setMinutes(dateOut.getMinutes() + (mins-0));
            } else {
                dateOut.setHours(dateOut.getHours() - hours);
                dateOut.setMinutes(dateOut.getMinutes() - mins);
            }
            return dateOut;
        },

        _getDatePart: function(part, digits){
            part = part.toString();
            while(part.length < digits) {
                part = '0' + part;
            }
            return part;
        },

        _getDateDiff: function(startDate, endDate) {
            var diff = Math.floor((endDate - startDate)/60000),
            hours = Math.floor(diff/60),
            mins = diff - (hours * 60);
            return this._getDatePart(hours,2) + this._getDatePart(mins,2);
        },

        _getUrl_ics: function() {
            var data = this.options.data,
            url = this.options.ics;

            url += (url.indexOf('?') === -1) ? '?' : '&';
            url += 'title=' + encodeURIComponent(data.title);
            url += '&desc=' + encodeURIComponent(data.desc);
            url += '&start=' + this._getUTCTime(data.timeObj.start);
            url += '&end=' + this._getUTCTime(data.timeObj.end);
            url += '&loc=' + encodeURIComponent(data.location);
            url += '&org=' + encodeURIComponent(data.organizer.name);
            url += '&url=' + encodeURIComponent(data.url);
            url += '&offset=' + new Date().getTimezoneOffset();
            return url;
        },

        _getUrl_google: function() {
            var data = this.options.data,
            url = 'http://www.google.com/calendar/event?action=TEMPLATE';
            url += '&text=' + encodeURIComponent(data.title);
            url += '&details=' + encodeURIComponent(data.desc);
            url += '&location=' + encodeURIComponent(data.location);
            url += '&dates=' + encodeURIComponent(this._getUTCTime(data.timeObj.start) + '/' + this._getUTCTime(data.timeObj.end));  // time needs to be sent as UTC and let Google handle converting to local
            url += '&sprop=website:' + encodeURIComponent(data.url);
            url += '&sprop=name:' + encodeURIComponent(data.organizer.name);
            return url;
        },
        _getUrl_yahoo: function() {
            var data = this.options.data,
            url = 'http://calendar.yahoo.com?v=60';
            url += '&TITLE=' + encodeURIComponent(data.title);
            url += '&DESC=' + encodeURIComponent(data.desc);
            url += '&URL=' + encodeURIComponent(data.url);
            url += '&in_loc=' + encodeURIComponent(data.location);
            url += '&ST=' + this._getUTCTime(data.timeObj.start);
            url += '&DUR=' + this._getDateDiff(data.timeObj.start, data.timeObj.end);
            return url;
        },
        _getUrl_hotmail: function() {
            var data = this.options.data,
            url = 'https://outlook.live.com/owa/?rru=addevent';
            url += '&subject=' + encodeURIComponent(data.title);
            url += '&location=' + encodeURIComponent(data.location);
            url += '&startdt=' + this._getUTCTime(data.timeObj.start);
            url += '&enddt=' + this._getUTCTime(data.timeObj.end);
            return url;
        },

        _eventPublisher: function(evt, evtObj) {
            evtObj = evtObj || {};
            evtObj.buttonId = this.el.attr('id');
            evtObj.data = this.options.data;
            $(document).trigger(evt, evtObj);
            // if(window.console){
            //     window.console.log(evt);
            //     window.console.log(evtObj);
            // }
        },

    /*
    ----------------------------
    Public methods
    ----------------------------
    */

    getEventData: function(returnObj) {
            this._sanitizeData();
            returnObj.data = this.options.data;
        },

        update: function(options){
            this._update(options);
        }
    };


  /*
  ----------------------------
  Function
  ----------------------------
  */

  $.fn.addcalevent = function addcalevent_init(options) {

    var thisCall = typeof options;

    switch (thisCall) {

            // allow users to call a specific public method
        case 'string':
            var args = Array.prototype.slice.call(arguments, 1);
            try{
                this.each(function () {
                    var instance = $.data(this, 'addcalevent');
                    if (!instance) {
                        throw 'Method ' + options + ' cannot be called until addcalevent is setup';
                    }
                    if (!$.isFunction(instance[options]) || options.charAt(0) === '_') {
                        throw 'No such public method ' + options + ' for addcalevent';
                    }
                    // no errors!
                    instance[options].apply(instance, args);
                });
            } catch(err){
                // if(window.console){
                //     window.console.log(err);
                // }
                return false;
            }
            break;

      // attempt to create
        case 'undefined':
        case 'object':
            this.each(function () {
                var instance = $.data(this, 'addcalevent');
                if (instance) {
                    // update options of current instance
                    instance.update(options);
                } else {
                    // initialize new instance
                    instance = new $.addcalevent(options, this);
                    // don't attach if instantiation failed
                    if (!instance.failed) {
                        $.data(this, 'addcalevent', instance);
                    }
                }
            });
            break;

        }
        return this;
    };

})(window, jQuery);
