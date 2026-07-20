const FOLDER_ID = '1JsZ4UQfn94aQXJC1KXyraSqqN-eoIJaL';
const USERS = ['yeop', 'yeom', 'yeong'];

function doGet(e) {
  try {
    const teacher = normalizeTeacher_(e && e.parameter ? e.parameter.teacher : '');
    const file = getOrCreateTeacherFile_(teacher);
    const text = file.getBlob().getDataAsString('UTF-8') || '{}';
    return jsonResponse_({
      ok: true,
      teacher: teacher,
      data: JSON.parse(text),
      updatedAt: file.getLastUpdated().toISOString()
    });
  } catch (error) {
    return jsonResponse_({ ok: false, error: String(error) });
  }
}

function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      throw new Error('저장할 데이터가 없습니다.');
    }
    const request = JSON.parse(e.postData.contents);
    const teacher = normalizeTeacher_(request.teacher);
    const data = Object.prototype.hasOwnProperty.call(request, 'data')
      ? request.data
      : request;
    const file = getOrCreateTeacherFile_(teacher);
    file.setContent(JSON.stringify(data, null, 2));
    return jsonResponse_({
      ok: true,
      teacher: teacher,
      updatedAt: file.getLastUpdated().toISOString()
    });
  } catch (error) {
    return jsonResponse_({ ok: false, error: String(error) });
  }
}

function normalizeTeacher_(value) {
  const teacher = String(value || '').trim().toLowerCase();
  if (USERS.indexOf(teacher) === -1) {
    throw new Error('teacher는 yeop, yeom, yeong 중 하나여야 합니다.');
  }
  return teacher;
}

function getOrCreateTeacherFile_(teacher) {
  const folder = DriveApp.getFolderById(FOLDER_ID);
  const fileName = teacher + '.json';
  const files = folder.getFilesByName(fileName);
  if (files.hasNext()) return files.next();

  // 기존 단일 파일을 사용 중이었다면 yeop.json 최초 생성 시 한 번 복사합니다.
  if (teacher === 'yeop') {
    const legacy = folder.getFilesByName('academy_data.json');
    if (legacy.hasNext()) {
      const text = legacy.next().getBlob().getDataAsString('UTF-8') || '{}';
      return folder.createFile(fileName, text, MimeType.PLAIN_TEXT);
    }
  }
  return folder.createFile(fileName, '{}', MimeType.PLAIN_TEXT);
}

function jsonResponse_(value) {
  return ContentService
    .createTextOutput(JSON.stringify(value))
    .setMimeType(ContentService.MimeType.JSON);
}
