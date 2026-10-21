package org.mehrchat.preview;

import android.app.Service;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Matrix;
import android.media.*;
import android.os.*;
import android.util.Base64;
import org.json.*;
import java.io.*;
import java.nio.*;
import java.util.concurrent.*;
import java.util.zip.DeflaterOutputStream;

/** No permissions, no vault/filesystem/network access. Only bounded input pipes. */
public final class PreviewService extends Service {
    private final ExecutorService executor=Executors.newSingleThreadExecutor();
    private final Messenger endpoint=new Messenger(new Handler(Looper.getMainLooper()) {
        @Override public void handleMessage(Message message) {
            if(message.what==99){ android.os.Process.killProcess(android.os.Process.myPid());return; }
            final Bundle args=message.getData();
            args.setClassLoader(ParcelFileDescriptor.class.getClassLoader());
            final ParcelFileDescriptor fd=args.getParcelable("input");
            final ParcelFileDescriptor output=args.getParcelable("output");
            final String kind=args.getString("kind","");
            executor.submit(()->{
                String result="";
                try(ParcelFileDescriptor.AutoCloseInputStream input=new ParcelFileDescriptor.AutoCloseInputStream(fd)) {
                    ByteArrayOutputStream bytes=new ByteArrayOutputStream();byte[] buffer=new byte[8192];int n;
                    while((n=input.read(buffer))!=-1){if(bytes.size()+n>4*1024*1024)throw new IOException();bytes.write(buffer,0,n);}
                    byte[] raw=bytes.toByteArray();JSONObject value;
                    if(kind.equals("probe")){
                        boolean denied=false;
                        String canary=new String(raw,java.nio.charset.StandardCharsets.UTF_8);
                        try(FileInputStream secret=new FileInputStream(canary)){secret.read();}catch(Exception expected){denied=true;}
                        value=new JSONObject();value.put("files_denied",denied);value.put("uid_isolated",android.os.Process.myUid()!=getApplicationInfo().uid);
                    }
                    else if(kind.equals("image")) value=image(raw);
                    else if(kind.equals("video")||kind.equals("audio"))value=av(raw,kind);
                    else throw new IOException();
                    result=value.toString();if(result.length()>272048)result="";
                }catch(Exception|OutOfMemoryError failure){result="";android.util.Log.w("MehrPreview","Decoder rejected "+failure.getClass().getSimpleName());}
                try(OutputStream stream=new ParcelFileDescriptor.AutoCloseOutputStream(output)){
                    stream.write(result.getBytes(java.nio.charset.StandardCharsets.UTF_8));
                }catch(IOException ignored){}
            });
        }
    });
    @Override public IBinder onBind(Intent intent){return endpoint.getBinder();}
    @Override public void onDestroy(){executor.shutdownNow();super.onDestroy();}
    private static JSONObject raster(Bitmap bitmap,String kind,double duration)throws Exception {
        if(bitmap==null)throw new IOException();
        int w=bitmap.getWidth(),h=bitmap.getHeight();
        if(w<=0||h<=0)throw new IOException();
        if(w>256||h>256){double scale=Math.min(256.0/w,256.0/h);Bitmap small=Bitmap.createScaledBitmap(bitmap,Math.max(1,(int)(w*scale)),Math.max(1,(int)(h*scale)),true);if(small!=bitmap)bitmap.recycle();bitmap=small;w=bitmap.getWidth();h=bitmap.getHeight();}
        int[] pixels=new int[w*h];bitmap.getPixels(pixels,0,w,0,0,w,h);bitmap.recycle();
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();
        {
            for(int p:pixels){bytes.write((p>>>16)&255);bytes.write((p>>>8)&255);bytes.write(p&255);}
        }
        JSONObject value=new JSONObject();value.put("v",1);value.put("kind",kind);value.put("width",w);value.put("height",h);
        value.put("rgb",Base64.encodeToString(bytes.toByteArray(),Base64.NO_WRAP));value.put("duration",Math.min(86400,Math.max(0,duration)));return value;
    }
    private static JSONObject image(byte[] raw)throws Exception {
        BitmapFactory.Options options=new BitmapFactory.Options();options.inJustDecodeBounds=true;
        BitmapFactory.decodeByteArray(raw,0,raw.length,options);
        if(options.outWidth<=0||options.outHeight<=0||(long)options.outWidth*options.outHeight>12000000||Math.max(options.outWidth,options.outHeight)>16384)throw new IOException();
        if(!("image/jpeg".equals(options.outMimeType)||"image/png".equals(options.outMimeType)||"image/gif".equals(options.outMimeType)||"image/webp".equals(options.outMimeType)))throw new IOException();
        options.inJustDecodeBounds=false;options.inPreferredConfig=Bitmap.Config.ARGB_8888;options.inSampleSize=1;
        while(options.outWidth/options.inSampleSize>256||options.outHeight/options.inSampleSize>256)options.inSampleSize*=2;
        Bitmap bitmap=BitmapFactory.decodeByteArray(raw,0,raw.length,options);
        if(bitmap==null)throw new IOException();
        try {
            ExifInterface exif=new ExifInterface(new ByteArrayInputStream(raw));int orientation=exif.getAttributeInt(ExifInterface.TAG_ORIENTATION,1);
            Matrix matrix=new Matrix();
            if(orientation==3)matrix.postRotate(180);else if(orientation==6)matrix.postRotate(90);else if(orientation==8)matrix.postRotate(270);
            else if(orientation==2)matrix.postScale(-1,1);else if(orientation==4)matrix.postScale(1,-1);
            else if(orientation==5){matrix.postRotate(90);matrix.postScale(-1,1);}else if(orientation==7){matrix.postRotate(270);matrix.postScale(-1,1);}
            if(!matrix.isIdentity()){Bitmap corrected=Bitmap.createBitmap(bitmap,0,0,bitmap.getWidth(),bitmap.getHeight(),matrix,true);if(corrected!=bitmap)bitmap.recycle();bitmap=corrected;}
        }catch(IOException ignored){}
        return raster(bitmap,"image",0);
    }
    private static final class Source extends MediaDataSource {
        private final byte[] raw;Source(byte[] value){raw=value;}
        public int readAt(long position,byte[] buffer,int offset,int size){if(position<0||position>=raw.length)return -1;int count=Math.min(size,raw.length-(int)position);System.arraycopy(raw,(int)position,buffer,offset,count);return count;}
        public long getSize(){return raw.length;}public void close(){}
    }
    private static JSONObject av(byte[] raw,String kind)throws Exception {
        MediaMetadataRetriever retriever=new MediaMetadataRetriever();
        try {
            retriever.setDataSource(new Source(raw));String length=retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION);
            double duration=length==null?0:Math.min(86400,Math.max(0,Long.parseLong(length)/1000.0));
            if(kind.equals("video")){
                if(Build.VERSION.SDK_INT<27)throw new IOException();
                return raster(retriever.getScaledFrameAtTime(0,MediaMetadataRetriever.OPTION_CLOSEST_SYNC,256,256),kind,duration);
            }
            JSONObject result=new JSONObject();result.put("v",1);result.put("kind","audio");result.put("duration",duration);result.put("waveform",waveform(raw));return result;
        } finally { retriever.release(); }
    }
    private static JSONArray waveform(byte[] raw)throws Exception {
        MediaExtractor extractor=new MediaExtractor();MediaCodec codec=null;int[] peaks=new int[64];int used=0;
        try {
            extractor.setDataSource(new Source(raw));MediaFormat format=null;
            for(int i=0;i<extractor.getTrackCount();i++){MediaFormat f=extractor.getTrackFormat(i);if(f.getString(MediaFormat.KEY_MIME).startsWith("audio/")){format=f;extractor.selectTrack(i);break;}}
            if(format==null)throw new IOException();
            int rate=format.getInteger(MediaFormat.KEY_SAMPLE_RATE),channels=format.getInteger(MediaFormat.KEY_CHANNEL_COUNT);
            if(rate<4000||rate>192000||channels<1||channels>8)throw new IOException();
            if("audio/raw".equals(format.getString(MediaFormat.KEY_MIME))){
                // PCM from WAV is already decoded by the extractor. Android
                // does not provide a MediaCodec decoder for audio/raw.
                ByteBuffer input=ByteBuffer.allocate(65536).order(ByteOrder.LITTLE_ENDIAN);
                int encoding=format.containsKey(MediaFormat.KEY_PCM_ENCODING)?format.getInteger(MediaFormat.KEY_PCM_ENCODING):AudioFormat.ENCODING_PCM_16BIT;
                if(encoding!=AudioFormat.ENCODING_PCM_16BIT&&encoding!=AudioFormat.ENCODING_PCM_FLOAT)throw new IOException();
                long samples=0,deadline=System.nanoTime()+6_000_000_000L;
                while(System.nanoTime()<deadline&&samples<(long)rate*channels*30){
                    input.clear();int n=extractor.readSampleData(input,0);if(n<=0)break;input.position(0);input.limit(n);
                    while(input.remaining()>=(encoding==AudioFormat.ENCODING_PCM_FLOAT?4:2)&&samples<(long)rate*channels*30){
                        float amplitude=encoding==AudioFormat.ENCODING_PCM_FLOAT?Math.abs(input.getFloat()):Math.abs((int)input.getShort())/32768f;
                        int bucket=(int)Math.min(63,samples*2/((long)rate*channels));peaks[bucket]=Math.max(peaks[bucket],Math.min(255,(int)(amplitude*255)));used=Math.max(used,bucket+1);samples++;
                    }
                    if(!extractor.advance())break;
                }
                if(used==0)throw new IOException();
                JSONArray result=new JSONArray();for(int i=0;i<used;i++)result.put(peaks[i]);return result;
            }
            codec=MediaCodec.createDecoderByType(format.getString(MediaFormat.KEY_MIME));codec.configure(format,null,null,0);codec.start();
            MediaCodec.BufferInfo info=new MediaCodec.BufferInfo();boolean inputDone=false,done=false;long samples=0,deadline=System.nanoTime()+6_000_000_000L;
            while(!done&&System.nanoTime()<deadline&&samples<(long)rate*channels*30){
                if(!inputDone){int index=codec.dequeueInputBuffer(10000);if(index>=0){ByteBuffer input=codec.getInputBuffer(index);int n=extractor.readSampleData(input,0);if(n<0){codec.queueInputBuffer(index,0,0,0,MediaCodec.BUFFER_FLAG_END_OF_STREAM);inputDone=true;}else{codec.queueInputBuffer(index,0,n,extractor.getSampleTime(),0);extractor.advance();}}}
                int index=codec.dequeueOutputBuffer(info,10000);
                if(index>=0){ByteBuffer output=codec.getOutputBuffer(index);output.position(info.offset);output.limit(info.offset+info.size);output.order(ByteOrder.LITTLE_ENDIAN);
                    MediaFormat decoded=codec.getOutputFormat();int encoding=decoded.containsKey(MediaFormat.KEY_PCM_ENCODING)?decoded.getInteger(MediaFormat.KEY_PCM_ENCODING):AudioFormat.ENCODING_PCM_16BIT;
                    while(output.remaining()>=(encoding==AudioFormat.ENCODING_PCM_FLOAT?4:2)){
                        float amplitude=encoding==AudioFormat.ENCODING_PCM_FLOAT?Math.abs(output.getFloat()):Math.abs((int)output.getShort())/32768f;
                        int bucket=(int)Math.min(63,samples*2/((long)rate*channels));peaks[bucket]=Math.max(peaks[bucket],Math.min(255,(int)(amplitude*255)));used=Math.max(used,bucket+1);samples++;
                    }
                    done=(info.flags&MediaCodec.BUFFER_FLAG_END_OF_STREAM)!=0;codec.releaseOutputBuffer(index,false);
                }
            }
        }finally{if(codec!=null){try{codec.stop();}catch(Exception ignored){}codec.release();}extractor.release();}
        JSONArray result=new JSONArray();for(int i=0;i<used;i++)result.put(peaks[i]);return result;
    }
}
