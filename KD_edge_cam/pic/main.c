/*
 * PIC12F629 Power Controller for Trail Camera
 *
 * コンパイラ: XC8 (Microchip)
 * ターゲット: PIC12F629
 *
 * 概要:
 * PIRセンサーからの割り込み検知のみでスリープから復帰し、
 * MOSFETをONにしてESP32システム全体へ給電する極低消費電力の電源管理プログラム。
 * ESP32からの処理完了信号(または3分タイムアウト)でMOSFETをOFFにして再度スリープへ入る。
 * WDT(ウォッチドッグタイマー)を有効化し、信頼性向上と待機時のスリープ化による省電力を実現。
 */

// --- コンフィグレーションビットの設定 ---
#pragma config FOSC = INTRCIO // 内部オシレータ使用 (GP4/GP5はデジタルI/Oとして使用)
#pragma config WDTE = ON      // ウォッチドッグタイマー有効 (フリーズ対策 兼 スリープ時のタイマー)
#pragma config PWRTE = ON     // パワーアップタイマー有効
#pragma config MCLRE = OFF    // GP3/MCLRピンはデジタル入力として使用(内部でVDDにプルアップ)
#pragma config BOREN = OFF    // ブラウンアウト・リセット無効
#pragma config CP = OFF       // コードプロテクト無効
#pragma config CPD = OFF      // データプロテクト無効

#include <stdint.h>
#include <xc.h>

// 内部クロック周波数の定義 (__delay_ms()関数で使用)
#define _XTAL_FREQ 4000000 // 4MHz

// --- ピン割り当て ---
#define PIN_MOSFET     GP0 // 出力: xiaoの電源制御 (HIGHでMOSFET ON)
#define PIN_XIAO_DONE  GP1 // 入力/出力: xiaoからの完了信号(入力) / フローティング防止(出力LOW)
#define PIN_PIR        GP2 // 入力: PIRセンサー (状態変化割り込み INT を使用)
#define PIN_XIAO_SIG   GP4 // 出力: xiaoへの信号
#define PIN_LED        GP5 // 出力: LED

// --- パラメータ設定 ---
// タイムアウト時間: 3分 = 180秒 (100ms * 1800回)
#define TIMEOUT_MAX_COUNT 1800

// 撮影後インターバル: 3分30秒 = 210秒
// WDTプリスケーラ1:128の場合、1回のタイムアウトは約2.3秒
// 210秒 / 2.3秒 ≒ 91回
#define INTERVAL_WDT_CYCLES 91

// --- 関数定義 ---
// LEDを指定回数、指定間隔(ms)で点滅させる（WDTクリア付き）
void blink_led(uint8_t count, uint16_t delay_ms) {
    uint16_t loops = delay_ms / 10;
    if (loops == 0) loops = 1;
    
    for (uint8_t i = 0; i < count; i++) {
        PIN_LED = 1;
        for(uint16_t j = 0; j < loops; j++) {
            __delay_ms(10);
            CLRWDT();
        }
        PIN_LED = 0;
        for(uint16_t j = 0; j < loops; j++) {
            __delay_ms(10);
            CLRWDT();
        }
    }
}

void main(void) {
    // --- 初期化 ---
    // コンパレータの無効化（デジタルI/Oとして使うため必須）
    CMCON = 0x07;

    // GPIOの初期出力値設定 (すべてLOW)
    GPIO = 0x00;
    
    // WDT用プリスケーラの設定 (OPTION_REG)
    // PSA(bit3)=1(WDTに割り当て), PS2-PS0(bit2-0)=111 (1:128)
    // これによりWDTタイムアウトは約2.3秒(Typ)となる。
    OPTION_REGbits.PSA = 1;
    OPTION_REGbits.PS = 0b111;

    // GPIOの入出力方向設定 (0=出力, 1=入力)
    // GP0(MOSFET) = 出力(0)
    // GP1(XIAO_DONE) = 最初は出力(0)にしてLOW固定（フローティング対策）
    // GP2(PIR) = 入力(1)
    // GP3(MCLR) = 入力(1) - 入力専用
    // GP4(XIAO_SIG), GP5(LED) = 出力(0)
    TRISIO = 0b00001100; // GP1を出力(0)に変更

    // --- デバッグ用：起動確認のLED点滅 (3回、200ms間隔) ---
    blink_led(3, 200);

    // --- PIRセンサー安定化待ち (約30秒) ---
    // 待機中はLEDを約2秒周期でゆっくり点滅
    for (uint8_t i = 0; i < 15; i++) {
        blink_led(1, 1000);
    }

    // --- 割り込み設定 (INT割り込みを使用) ---
    OPTION_REGbits.INTEDG = 1; // 立ち上がりエッジ（LOWからHIGHになった瞬間）で割り込み
    GIE = 0;  // スリープからそのまま復帰させるため全体割り込みは無効(0)

    // --- メインループ ---
    while (1) {
        // 1. xiaoへの給電等をOFF
        PIN_MOSFET = 0;
        PIN_XIAO_SIG = 0;
        PIN_LED = 0;
        
        // フローティング対策: ESP32電源OFF時はGP1(XIAO_DONE)を出力LOWにする
        TRISIO = 0b00001100; // GP1を出力に設定
        PIN_XIAO_DONE = 0;

        // 2. 超低消費電力スリープモードへ移行
        INTE = 1; // INT外部割り込み許可
        INTF = 0; // INT割り込みフラグをクリア
        
        // PIRがLOWなら安心してスリープ
        if (PIN_PIR == 0) {
            // WDT有効のため約2.3秒おきに起床するが、PIR検知(INTF=1)までは再スリープ
            while (INTF == 0) {
                CLRWDT();
                SLEEP();
            }
        }
        
        // 割り込み禁止（以後の処理中やインターバル中に誤検知しないため）
        INTE = 0;

        // ------------------------------------------------
        // 3. スリープから復帰（PIR検知確定）
        // ------------------------------------------------

        // チャタリングや一瞬のノイズ(静電気等)による誤作動を防ぐため少し待機
        for(uint8_t i=0; i<5; i++) {
            __delay_ms(10);
            CLRWDT();
        }

        // 50ms後もまだPIRがHIGHのままであれば本物の検知とみなす
        if (PIN_PIR == 1) {
            // ESP32起動前にフローティング対策を解除し、GP1(XIAO_DONE)を入力に戻す
            TRISIO = 0b00001110; // GP1を入力に

            // すぐに xiaoへの給電をON、信号出力
            PIN_MOSFET = 1;
            PIN_XIAO_SIG = 1;
            PIN_LED = 1;

            // ESP32がブートし、ピン状態が安定するまで待機（起動直後の誤検知防止）
            // 待機中はLEDを細かく点滅 (約3秒)
            blink_led(15, 100);

            // 4. xiaoの処理完了またはタイムアウト(3分)待ちループ
            uint16_t timeout_counter = 0;
            while (timeout_counter < TIMEOUT_MAX_COUNT) {
                CLRWDT();
                
                // xiaoから「処理完了」のHIGH信号が来たら抜ける
                if (PIN_XIAO_DONE == 1) {
                    break;
                }

                __delay_ms(100);
                timeout_counter++;

                // 処理待ち中はLEDを点滅 (500ms周期)
                if (timeout_counter % 5 == 0) {
                    PIN_LED ^= 1;
                }
            }

            // 5. 処理完了またはタイムアウト。出力をOFFにして再度スリープの準備へ
            PIN_MOSFET = 0;
            PIN_XIAO_SIG = 0;
            PIN_LED = 0;
            
            // 再びフローティング対策
            TRISIO = 0b00001100; // GP1を出力に
            PIN_XIAO_DONE = 0;

            // 6. 連続撮影を防ぐインターバル (3分30秒)
            // 約2.3秒(WDT) × 91回 ＝ 約210秒(3.5分)
            for (uint16_t i = 0; i < INTERVAL_WDT_CYCLES; i++) {
                // デバッグ用: インターバル中は約4.6秒(2周期)ごとにチカッと短く点滅
                if (i % 2 == 0) {
                    PIN_LED = 1;
                    __delay_ms(10);
                    PIN_LED = 0;
                }
                
                CLRWDT();
                SLEEP(); // 約2.3秒スリープ
            }
            
            PIN_LED = 0; // 最後に確実に消灯
        }
    }
}
