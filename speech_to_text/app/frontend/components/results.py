"""
Results component for displaying transcription history
"""
import streamlit as st


def render_results_section():
    """Render the results section with transcription history"""
    st.header("📝 ผลลัพธ์")
    
    # Display transcription history
    if st.session_state.transcription_history:
        for i, item in enumerate(reversed(st.session_state.transcription_history)):
            # Create title with filename if available
            if item.get('filename'):
                title = f"📄 {item['filename']} ({item['time']})"
            elif item.get('source') == 'recording':
                title = f"🎙️ บันทึกเสียง ({item['time']})"
            else:
                title = f"🕐 {item['time']}"
            
            with st.expander(title, expanded=(i==0)):
                st.write("**การถอดเสียง:**")
                st.write(item['text'])
                
                # Copy button
                if st.button(f"📋 คัดลอก", key=f"copy_{i}"):
                    st.write("คัดลอกแล้ว!")
    else:
        st.info("ยังไม่มีผลลัพธ์การถอดเสียง")

