/* 高さを揃える */
$(function(){
	'use strict';
	$('.search_valiation-2-menu-item').matchHeight(); // 組織別から探すメガメニュー
	$('.is_gnav_nav-mega1 > ul').matchHeight(); // 各メガメニュー
	$('.is_gnav_nav-mega2 > ul').matchHeight();
	$('.is_gnav_nav-mega3 > ul').matchHeight();
	$('.is_gnav_nav-mega4 > ul').matchHeight();
	$('.is_gnav_nav-mega5 > ul').matchHeight();
});

/* 組織別から探すメガメニュー */
$(function(){
	'use strict';
	var searchValidation2Menu = $('.search_valiation-2-menu');
	$('.search_valiation-2 > a').on('click', function(e){
		e.preventDefault();
		searchValidation2Menu.removeClass('is_search_valiation-2-menu_focus');
		if (searchValidation2Menu.hasClass('is_search_valiation-2-menu_click')){
			searchValidation2Menu.removeClass('is_search_valiation-2-menu_click');
		} else {
			searchValidation2Menu.addClass('is_search_valiation-2-menu_click');
		}
	});
	$('.search_valiation-2-menu-close > a').on('click', function(e){
		e.preventDefault();
		searchValidation2Menu.removeClass('is_search_valiation-2-menu_click is_search_valiation-2-menu_focus');
	});
	// フォーカス tabフォーカス対応
	$('.search_valiation-2 > a').on('focus', function() {
		searchValidation2Menu.addClass('is_search_valiation-2-menu_focus');	
	});
	$('.search_valiation-1 > a').on('focus', function() {
		searchValidation2Menu.removeClass('is_search_valiation-2-menu_focus');
	});
	$('.search_form input	').on('focus', function() {
		searchValidation2Menu.removeClass('is_search_valiation-2-menu_focus');
	});
	// ３列目要素
	$('.search_valiation-2-menu-item:nth-child(3n+1)').addClass('is_search_valiation-2-menu-item');
	// 最下行要素
	$('.search_valiation-2-menu-item:nth-child(n+8)').addClass('is_search_valiation-2-menu-item-lastrow');
});

/* "質問"と"答え"文言挿入 */
$(function(){
	'use strict';
	$('.faq dt').prepend('<span class="sr_only">質問</span>');
	$('.faq dd').prepend('<span class="sr_only">答え</span>');
});

/* faq詳細ページ サブメニューよりのスクロール
 *（上から数えてn番目のサブメニューに対して、上から数えてn番目の.faqコンテンツへスクロールする 
 */
$(function(){
	'use strict';
	$('.is_side_menu_item').on('click', function(){
		var n = $('.is_side_menu_item').index(this); // 上から数えてn番目のサブメニューを取得
		var place = $('.faq').eq(n).offset().top; // 上から数えてn番目の.faqの位置を取得
		$('html, body').animate({scrollTop: place - 10}, 'fast');
		return false;
	});
});
